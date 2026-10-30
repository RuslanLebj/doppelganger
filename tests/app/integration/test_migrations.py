from alembic import command
from alembic.config import Config
from conftest import PROJECT
from sqlalchemy import inspect, text

from app.infrastructure.db.models import BackupRun
from db.postgresql.engine import make_engine


def test_postgresql_schema_matches_models(settings, sessions):
    command.check(Config(str(PROJECT / "src/alembic.ini")))
    engine = make_engine(settings)
    try:
        inspector = inspect(engine)
        assert set(inspector.get_table_names()) == {
            "alembic_version",
            "database_target",
            "backup_plan",
            "backup_run",
        }
        columns = {column["name"] for column in inspector.get_columns("backup_run")}
        assert {"s3_key", "s3_status"} <= columns
        assert not {"local_key", "local_status"} & columns
        assert "stage" not in columns
        assert (
            inspector.get_foreign_keys("backup_plan")[0]["referred_table"]
            == "database_target"
        )
    finally:
        engine.dispose()


def test_single_storage_migration_preserves_history(settings, sessions, source):
    key = "postgres-backups/history/target-1/run-1.dump"
    with sessions.begin() as session:
        run = BackupRun(
            plan_id=source[1].id, status="success", s3_key=key, s3_status="success"
        )
        session.add(run)
    config = Config(str(PROJECT / "src/alembic.ini"))
    command.downgrade(config, "pg_0001")
    engine = make_engine(settings)
    try:
        with engine.connect() as connection:
            assert connection.execute(
                text("SELECT local_key, local_status FROM backup_run WHERE id = :id"),
                {"id": run.id},
            ).one() == (key, "success")
        command.upgrade(config, "head")
        with sessions() as session:
            restored = session.get(BackupRun, run.id)
            assert (restored.s3_key, restored.s3_status, restored.status) == (
                key,
                "success",
                "success",
            )
    finally:
        engine.dispose()
