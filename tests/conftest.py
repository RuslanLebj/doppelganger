import os
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from psycopg import sql

from app.application.services.schedules import next_fire
from app.infrastructure.db.models import BackupPlan, DatabaseTarget
from app.infrastructure.db.models.base import utcnow
from bootstrap.rest import create_app
from config import Settings
from db.postgresql.engine import make_engine, make_session_factory
from utils.cryptography.fernet import SecretCipher

PROJECT = Path(__file__).resolve().parents[1]
TEST_PASSWORD = "only-a-test:password\\with-symbols"
TOKEN = "test-api-token-" * 4


@pytest.fixture
def settings(tmp_path):
    settings = Settings(
        _env_file=None,
        DATA_DIR=tmp_path / "data",
        CRYPT_KEY=Fernet.generate_key().decode(),
        API_KEY=TOKEN,
        ADMIN_USERNAME="test-admin",
        ADMIN_PASSWORD="test-admin-password",
        ADMIN_SESSION_SECRET_KEY="test-session-signing-key-at-least-32-characters",
        POSTGRES_DB_HOST="127.0.0.1",
        POSTGRES_DB_PORT=int(os.environ.get("DOPPELGANGER_TEST_POSTGRES_PORT", "55433")),
        POSTGRES_DB_NAME=f"doppelganger_test_{uuid4().hex}",
        POSTGRES_DB_USER="doppelganger_test",
        POSTGRES_SSLMODE="disable",
        POSTGRES_DB_PASSWORD="test-only-password",
        S3_ACCESS_KEY="test",
        S3_SECRET_KEY="test",
        MIN_FREE_BYTES=0,
        BACKUP_EXECUTION_ENABLED=True,
    )
    settings.DATA_DIR.mkdir(mode=0o700)
    return settings


@pytest.fixture
def sessions(settings, monkeypatch):
    with psycopg.connect(
        host=settings.POSTGRES_DB_HOST,
        port=settings.POSTGRES_DB_PORT,
        dbname="postgres",
        user="doppelganger_test",
        password="test-only-password",
        autocommit=True,
    ) as admin:
        name = settings.POSTGRES_DB_NAME
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        engine = make_engine(settings)
        try:
            for key in (
                "POSTGRES_DB_HOST",
                "POSTGRES_DB_PORT",
                "POSTGRES_DB_NAME",
                "POSTGRES_DB_USER",
                "POSTGRES_SSLMODE",
            ):
                monkeypatch.setenv(key, str(getattr(settings, key)))
            monkeypatch.setenv(
                "POSTGRES_DB_PASSWORD", settings.POSTGRES_DB_PASSWORD.get_secret_value()
            )
            command.upgrade(Config(str(PROJECT / "src/alembic.ini")), "head")
            yield make_session_factory(engine)
        finally:
            engine.dispose()
            admin.execute(
                sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name))
            )


@pytest.fixture
def client(settings, sessions):
    with TestClient(create_app(settings)) as client:
        client.headers["X-API-Key"] = TOKEN
        yield client


@pytest.fixture
def source(sessions, settings):
    with sessions.begin() as session:
        target = DatabaseTarget(
            name="test-source",
            host="db.example.test",
            database="cashbox",
            username="backup",
            sslmode="verify-full",
            password_encrypted=SecretCipher(
                settings.CRYPT_KEY.get_secret_value()
            ).encrypt(TEST_PASSWORD),
        )
        session.add(target)
        session.flush()
        plan = BackupPlan(
            name="nightly",
            target_id=target.id,
            cron="0 2 * * *",
            timezone="Asia/Yekaterinburg",
            enabled=True,
            max_dump_seconds=60,
            lock_wait_seconds=5,
            next_run_at=next_fire("0 2 * * *", "Asia/Yekaterinburg", utcnow()),
        )
        session.add(plan)
    return target, plan
