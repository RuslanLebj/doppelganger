from alembic import context

from app.infrastructure.db.models import BackupPlan, BackupRun, DatabaseTarget  # noqa: F401
from app.infrastructure.db.models.base import BaseModel
from config import Settings
from db.postgresql.engine import make_engine

target_metadata = BaseModel.metadata


def run_migrations():
    engine = make_engine(Settings())
    with engine.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata, compare_type=True
        )
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


run_migrations()
