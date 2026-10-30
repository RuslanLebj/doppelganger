import logging
import shutil
from pathlib import Path
from threading import Event

from sqlalchemy import case, select, update

from app.infrastructure.backup.postgres import dump_database
from app.infrastructure.backup.process import CommandError, WorkerShutdown
from app.infrastructure.db.models import BackupPlan, BackupRun, DatabaseTarget
from app.infrastructure.db.models.base import utcnow
from app.infrastructure.s3.minio.adapter import S3Storage
from config import Settings
from utils.cryptography.fernet import SecretCipher

logger = logging.getLogger(__name__)


class BackupExecutor:
    def __init__(self, settings: Settings, session_factory, stop: Event):
        self.settings = settings
        self.sessions = session_factory
        self.stop = stop
        if settings.CRYPT_KEY is None:
            raise ValueError("CRYPT_KEY is required")
        self.cipher = SecretCipher(settings.CRYPT_KEY.get_secret_value())
        self.storage = S3Storage(settings, stop)

    def recover_interrupted(self):
        with self.sessions.begin() as session:
            session.execute(
                update(BackupRun)
                .where(BackupRun.status == "running")
                .values(
                    status="interrupted",
                    finished_at=utcnow(),
                    error="Worker stopped before this run completed",
                    s3_status=case(
                        (BackupRun.s3_status == "running", "interrupted"),
                        else_=BackupRun.s3_status,
                    ),
                )
            )

    def _save(self, run_id: int, **values):
        with self.sessions.begin() as session:
            session.execute(
                update(BackupRun).where(BackupRun.id == run_id).values(**values)
            )

    def _key(self, target_id: int, run_id: int):
        prefix = self.settings.S3_PREFIX.strip("/")
        return "/".join(
            part
            for part in [prefix, "history", f"target-{target_id}", f"run-{run_id}.dump"]
            if part
        )

    def _latest_key(self, target_id: int):
        prefix = self.settings.S3_PREFIX.strip("/")
        return "/".join(
            part
            for part in [prefix, "latest", f"target-{target_id}", "database.dump"]
            if part
        )

    def _newest_s3_run(self, target_id: int):
        with self.sessions() as session:
            return session.scalar(
                select(BackupRun.id)
                .join(BackupPlan)
                .where(
                    BackupPlan.target_id == target_id,
                    BackupRun.s3_status == "success",
                )
                .order_by(BackupRun.id.desc())
                .limit(1)
            )

    def execute_next(self) -> bool:
        if not self.settings.BACKUP_EXECUTION_ENABLED:
            return False
        # Caller owns the PostgreSQL advisory lock for the worker lifetime.
        with self.sessions.begin() as session:
            run = session.scalar(
                select(BackupRun)
                .where(BackupRun.status == "queued")
                .order_by(BackupRun.id)
                .limit(1)
                .with_for_update()
            )
            if run is None:
                return False
            plan = session.get(BackupPlan, run.plan_id)
            target = session.get(DatabaseTarget, plan.target_id)
            run.status = "running"
            run.started_at = utcnow()
            run.error = None

        operation = "dump"
        path: Path | None = None
        saved = run.s3_status == "success" and bool(run.s3_key)
        try:
            if run.dump_path:
                path = self.settings.DATA_DIR / run.dump_path
                if not path.is_file():
                    path = None
            if not saved:
                if path is None:
                    if run.dump_path or run.s3_status != "not_started":
                        raise CommandError(
                            "Staged dump is missing; a new backup must be requested"
                        )
                    if (
                        shutil.disk_usage(self.settings.DATA_DIR).free
                        < self.settings.MIN_FREE_BYTES
                    ):
                        raise CommandError("Insufficient local free space")
                    path = dump_database(
                        self.settings, self.cipher, target, plan, run.id, self.stop
                    )
                    self._save(
                        run.id,
                        dump_path=path.relative_to(self.settings.DATA_DIR).as_posix(),
                        dump_bytes=path.stat().st_size,
                    )
                operation = "upload"
                key = run.s3_key or self._key(target.id, run.id)
                self._save(run.id, s3_status="running", s3_key=key)
                self.storage.upload(path, key)
                if (self._newest_s3_run(target.id) or 0) <= run.id:
                    self.storage.promote(key, self._latest_key(target.id))
                self._save(run.id, s3_status="success")
                saved = True
            self._save(run.id, status="success", finished_at=utcnow())
            logger.info("Backup completed run_id=%s", run.id)
        except WorkerShutdown:
            values = {"s3_status": "interrupted"} if operation == "upload" else {}
            self._save(
                run.id,
                status="interrupted",
                finished_at=utcnow(),
                error="Worker stopped",
                **values,
            )
            raise
        except Exception as error:
            message = (
                str(error)
                if isinstance(error, CommandError)
                else "Internal error; inspect configuration and dependencies"
            )
            values = {"s3_status": "failed"} if operation == "upload" else {}
            self._save(
                run.id, status="failed", error=message, finished_at=utcnow(), **values
            )
            logger.error(
                "Backup failed run_id=%s error_type=%s", run.id, type(error).__name__
            )
        finally:
            if saved and path is not None:
                try:
                    path.unlink(missing_ok=True)
                    self._save(run.id, dump_path=None)
                except Exception:
                    logger.error("Temporary dump cleanup failed run_id=%s", run.id)
        return True
