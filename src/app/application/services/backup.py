from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.application.errors.backup import BackupConflict, BackupNotFound
from app.application.schemas.backup import PlanCreate, TargetCreate
from app.application.services.schedules import next_fire
from app.infrastructure.db.models import BackupPlan, BackupRun, DatabaseTarget
from app.infrastructure.db.models.base import utcnow
from config import Settings
from utils.cryptography.fernet import SecretCipher


class BackupService:
    def __init__(self, session: Session, settings: Settings, cipher: SecretCipher):
        self.session = session
        self.settings = settings
        self.cipher = cipher

    def _get(self, model, object_id: int, *, for_update: bool = False):
        instance = self.session.get(model, object_id, with_for_update=for_update)
        if instance is None:
            raise BackupNotFound("Object not found")
        return instance

    def _commit(self):
        try:
            self.session.commit()
        except IntegrityError:
            self.session.rollback()
            raise BackupConflict(
                "Duplicate name or an active run already exists"
            ) from None

    def targets(self):
        return self.session.scalars(
            select(DatabaseTarget).order_by(DatabaseTarget.id)
        ).all()

    def target_details(self, target_id: int):
        return self._get(DatabaseTarget, target_id)

    def save_target(self, data: TargetCreate, target_id: int | None = None):
        values = data.model_dump(exclude={"password"})
        target = (
            self._get(DatabaseTarget, target_id)
            if target_id is not None
            else DatabaseTarget()
        )
        for name, value in values.items():
            setattr(target, name, value)
        target.password_encrypted = self.cipher.encrypt(data.password.get_secret_value())
        self.session.add(target)
        self._commit()
        return target

    def change_password(self, target_id: int, password: str):
        target = self._get(DatabaseTarget, target_id)
        target.password_encrypted = self.cipher.encrypt(password)
        self._commit()

    def plans(self):
        return self.session.scalars(select(BackupPlan).order_by(BackupPlan.id)).all()

    def save_plan(self, data: PlanCreate, plan_id: int | None = None):
        self._get(DatabaseTarget, data.target_id)
        plan = (
            self._get(BackupPlan, plan_id, for_update=True)
            if plan_id is not None
            else BackupPlan()
        )
        if plan_id is not None and plan.target_id != data.target_id:
            if (
                self.session.scalar(
                    select(BackupRun.id).where(BackupRun.plan_id == plan_id).limit(1)
                )
                is not None
            ):
                raise BackupConflict(
                    "A plan with run history cannot be moved to another database; create a new plan"
                )
        for name, value in data.model_dump().items():
            setattr(plan, name, value)
        plan.next_run_at = next_fire(data.cron, data.timezone, utcnow())
        self.session.add(plan)
        self._commit()
        return plan

    def _check_execution(self):
        if not self.settings.BACKUP_EXECUTION_ENABLED:
            raise BackupConflict("Execution is disabled in configuration")

    def enqueue(self, plan_id: int):
        self._check_execution()
        # Serialize enqueue with plan edits so a history-bearing plan keeps its target.
        self._get(BackupPlan, plan_id, for_update=True)
        run = BackupRun(plan_id=plan_id)
        self.session.add(run)
        self._commit()
        return run

    def runs(self, plan_id: int | None, limit: int, offset: int):
        query = (
            select(BackupRun).order_by(BackupRun.id.desc()).limit(limit).offset(offset)
        )
        if plan_id is not None:
            query = query.where(BackupRun.plan_id == plan_id)
        return self.session.scalars(query).all()

    def run_details(self, run_id: int):
        return self._get(BackupRun, run_id)

    def retry_s3(self, run_id: int):
        self._check_execution()
        run = self._get(BackupRun, run_id, for_update=True)
        if run.status not in {"failed", "interrupted"} or not run.dump_path:
            raise BackupConflict("Retry requires a stopped run with a staged dump")
        if not (self.settings.DATA_DIR / run.dump_path).is_file():
            raise BackupConflict("Staged dump file is missing")
        run.status = "queued"
        run.error = None
        run.finished_at = None
        self._commit()
        return run
