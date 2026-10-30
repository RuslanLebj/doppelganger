import os
import tempfile
from pathlib import Path
from threading import Event

from app.infrastructure.backup.process import CommandError, base_environment, run_command
from app.infrastructure.db.models import BackupPlan, DatabaseTarget
from config import Settings
from utils.cryptography.fernet import SecretCipher


def escape_pgpass(value: str) -> str:
    return value.replace("\\", "\\\\").replace(":", "\\:")


def dump_database(
    settings: Settings,
    cipher: SecretCipher,
    target: DatabaseTarget,
    plan: BackupPlan,
    run_id: int,
    stop: Event,
) -> Path:
    directory = settings.BACKUPS_DIR / f"target-{target.id}"
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    final_path = directory / f"run-{run_id}.dump"
    partial_path = directory / f"run-{run_id}.dump.partial"
    if final_path.exists():
        raise CommandError("A completed dump already exists for this run")
    # Publish the complete file only after pg_dump has exited successfully.
    partial_path.unlink(missing_ok=True)
    fd = os.open(partial_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(fd)
    temporary = settings.DATA_DIR / "tmp"
    temporary.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        with tempfile.TemporaryDirectory(prefix="pgpass-", dir=temporary) as private:
            password_file = Path(private) / "pgpass"
            values = [
                target.host,
                str(target.port),
                target.database,
                target.username,
                cipher.decrypt(target.password_encrypted),
            ]
            fd = os.open(password_file, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            with os.fdopen(fd, "w") as stream:
                stream.write(":".join(map(escape_pgpass, values)) + "\n")
            env = base_environment() | {
                "PGHOST": target.host,
                "PGPORT": str(target.port),
                "PGDATABASE": target.database,
                "PGUSER": target.username,
                "PGSSLMODE": target.sslmode,
                "PGCONNECT_TIMEOUT": "10",
                "PGAPPNAME": f"doppelganger:run-{run_id}",
                "PGPASSFILE": str(password_file.resolve()),
            }
            run_command(
                [
                    settings.PG_DUMP_COMMAND,
                    "--no-password",
                    "--format=custom",
                    f"--compress={settings.DUMP_COMPRESSION_LEVEL}",
                    f"--lock-wait-timeout={plan.lock_wait_seconds}s",
                    f"--file={partial_path.resolve()}",
                ],
                env=env,
                timeout=plan.max_dump_seconds,
                stop=stop,
                work_dir=temporary,
                min_free_bytes=settings.MIN_FREE_BYTES,
            )
        with partial_path.open("rb") as stream:
            os.fsync(stream.fileno())
        partial_path.replace(final_path)
        directory_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        return final_path
    finally:
        partial_path.unlink(missing_ok=True)
