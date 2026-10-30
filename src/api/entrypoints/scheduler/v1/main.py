import logging
import os
import signal
from contextlib import contextmanager
from threading import Event

from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

from app.application.services.backups import BackupExecutor
from app.application.services.schedules import enqueue_due
from app.infrastructure.backup.process import WorkerShutdown
from app.infrastructure.db.models.base import utcnow
from config import Settings
from db.postgresql.engine import make_engine, make_session_factory


@contextmanager
def worker_lock(engine):
    # Session-level PostgreSQL lock works across hosts sharing the metadata database.
    key = 0x444F5050454C
    # The lock has its own connection, so even a metadata pool of size 1 remains usable.
    lock_engine = create_engine(engine.url, poolclass=NullPool, hide_parameters=True)
    try:
        with lock_engine.connect().execution_options(
            isolation_level="AUTOCOMMIT"
        ) as connection:
            if not connection.scalar(
                text("SELECT pg_try_advisory_lock(:key)"), {"key": key}
            ):
                raise RuntimeError("Another backup worker is already running") from None
            try:
                yield connection
            finally:
                connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": key})
    finally:
        lock_engine.dispose()


def run():
    os.umask(0o077)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    settings = Settings()
    if not settings.BACKUP_EXECUTION_ENABLED:
        raise SystemExit(
            "Execution disabled. Set BACKUP_EXECUTION_ENABLED=true after a supervised trial is planned."
        )
    stop = Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    engine = make_engine(settings)
    sessions = make_session_factory(engine)
    try:
        with worker_lock(engine) as lock_connection:
            executor = BackupExecutor(settings, sessions, stop)
            executor.recover_interrupted()
            while not stop.is_set():
                # Fail before starting another dump if PostgreSQL dropped the lock connection.
                lock_connection.execute(text("SELECT 1"))
                enqueue_due(sessions, utcnow())
                if not executor.execute_next():
                    stop.wait(settings.SCHEDULER_POLL_SECONDS)
    except WorkerShutdown:
        pass
    finally:
        engine.dispose()
