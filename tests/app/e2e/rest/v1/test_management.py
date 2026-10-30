from datetime import datetime, timedelta

import pytest
from conftest import TEST_PASSWORD
from cryptography.fernet import Fernet
from pydantic import ValidationError
from sqlalchemy import select, text

from api.entrypoints.scheduler.v1.main import worker_lock
from app.application.schemas.backup import PlanCreate
from app.application.services.schedules import enqueue_due
from app.infrastructure.db.models import BackupPlan, BackupRun, DatabaseTarget
from config import Settings
from db.postgresql.engine import make_engine
from utils.cryptography.fernet import SecretCipher


def test_password_is_encrypted_and_never_returned(client, sessions, settings):
    body = {
        "name": "cashbox",
        "host": "db.example.test",
        "database": "cashbox",
        "username": "backup",
        "password": TEST_PASSWORD,
    }
    response = client.post("/api/v1/targets", json=body)
    assert response.status_code == 201
    assert "password" not in response.text
    assert TEST_PASSWORD not in client.get("/api/v1/targets").text
    with sessions() as session:
        target = session.get(DatabaseTarget, response.json()["id"])
        assert target.password_encrypted != TEST_PASSWORD
        assert (
            SecretCipher(settings.CRYPT_KEY.get_secret_value()).decrypt(
                target.password_encrypted
            )
            == TEST_PASSWORD
        )
        with pytest.raises(ValueError, match="Cannot decrypt"):
            SecretCipher(Fernet.generate_key()).decrypt(target.password_encrypted)


def test_authentication_and_validation_do_not_echo_secrets(client):
    response = client.get("/api/v1/targets", headers={"Rosa-Api-Key": "incorrect"})
    assert response.status_code == 403
    body = {
        "name": "invalid",
        "host": "db.test",
        "database": "cashbox",
        "username": "backup",
        "password": {"nested": TEST_PASSWORD},
    }
    response = client.post("/api/v1/targets", json=body)
    assert response.status_code == 422
    assert TEST_PASSWORD not in response.text
    body.update(password=TEST_PASSWORD, database="host=another-server")
    assert client.post("/api/v1/targets", json=body).status_code == 422


def test_duplicate_runs_are_rejected_and_history_survives(client, source, sessions):
    _, plan = source
    first = client.post(f"/api/v1/plans/{plan.id}/runs")
    assert first.status_code == 202
    assert client.post(f"/api/v1/plans/{plan.id}/runs").status_code == 409
    with sessions() as session:
        run = session.get(BackupRun, first.json()["id"])
        assert run.status == "queued"
    history = client.get("/api/v1/runs").json()
    assert history[0]["id"] == first.json()["id"]
    assert history[0]["created_at"].endswith("Z")
    assert "stage" not in history[0]


def test_disabled_execution_never_enqueues(client, settings, source):
    settings.BACKUP_EXECUTION_ENABLED = False
    assert client.post(f"/api/v1/plans/{source[1].id}/runs").status_code == 409


def test_persisted_daily_schedule_coalesces_missed_nights(source, sessions):
    _, plan = source
    now = datetime(2026, 10, 28, 8, 0)
    with sessions.begin() as session:
        instance = session.get(BackupPlan, plan.id)
        instance.next_run_at = now - timedelta(days=4)
    assert enqueue_due(sessions, now) == 1
    assert enqueue_due(sessions, now) == 0
    assert enqueue_due(sessions, now + timedelta(days=1)) == 0
    with sessions() as session:
        assert len(session.scalars(select(BackupRun)).all()) == 1
        assert session.get(BackupPlan, plan.id).next_run_at > now + timedelta(days=1)


def test_schedule_is_daily_and_worker_is_singleton(settings, sessions):
    with pytest.raises(ValidationError):
        PlanCreate(name="too-often", target_id=1, cron="* * * * *")
    settings.POSTGRES_POOL_MAX_SIZE = 1
    engine = make_engine(settings)
    try:
        with worker_lock(engine):
            with engine.connect() as connection:
                assert connection.scalar(text("SELECT 1")) == 1
            with (
                pytest.raises(RuntimeError, match="already running"),
                worker_lock(engine),
            ):
                pass
        with worker_lock(engine):
            pass
    finally:
        engine.dispose()


def test_settings_mask_secrets(settings):
    displayed = repr(settings)
    for key in ("CRYPT_KEY", "API_KEY", "POSTGRES_DB_PASSWORD"):
        assert getattr(settings, key).get_secret_value() not in displayed


def test_single_s3_defaults_and_missing_credentials():
    settings = Settings(_env_file=None, S3_SECRET_KEY="")
    assert str(settings.S3_ENDPOINT) == "http://127.0.0.1:9000/"
    assert settings.RETENTION_DAYS == 7
    from app.infrastructure.s3.minio.adapter import open_client

    with pytest.raises(ValueError, match="S3_SECRET_KEY is required"):
        open_client(settings)


def test_api_key_header_matches_cashbox(client):
    client.headers.pop("Rosa-Api-Key")
    assert client.get("/api/v1/targets").status_code == 401
    assert client.get("/healthcheck/").json() == {"success": True, "msg": "App available"}
    assert client.get("/healthcheck/db").json() == {
        "success": True,
        "msg": "DB available",
    }


def test_target_password_update_and_not_found(client, sessions, settings, source):
    target, _ = source
    assert (
        client.put(
            f"/api/v1/targets/{target.id}/password", json={"password": "new-password"}
        ).status_code
        == 204
    )
    with sessions() as session:
        encrypted = session.get(DatabaseTarget, target.id).password_encrypted
        assert (
            SecretCipher(settings.CRYPT_KEY.get_secret_value()).decrypt(encrypted)
            == "new-password"
        )
    assert "new-password" not in client.get("/api/v1/targets").text
    assert client.get("/api/v1/runs/999999").status_code == 404
    assert (
        client.post(
            "/api/v1/plans", json={"name": "missing-target", "target_id": 999999}
        ).status_code
        == 404
    )


def test_plan_target_cannot_change_after_history_is_created(client, source):
    target, plan = source
    other = client.post(
        "/api/v1/targets",
        json={
            "name": "another",
            "host": "other.test",
            "database": "other",
            "username": "backup",
            "password": "secret",
        },
    ).json()
    body = {
        "name": plan.name,
        "target_id": other["id"],
        "cron": "0 3 * * *",
        "enabled": True,
    }
    # An unused plan may still be edited freely.
    assert client.put(f"/api/v1/plans/{plan.id}", json=body).status_code == 200
    assert client.post(f"/api/v1/plans/{plan.id}/runs").status_code == 202
    body["target_id"] = target.id
    assert client.put(f"/api/v1/plans/{plan.id}", json=body).status_code == 409
    assert client.get("/api/v1/plans").json()[0]["target_id"] == other["id"]
    # Schedule edits remain available without relabelling saved or queued dumps.
    body.update(target_id=other["id"], enabled=False)
    assert client.put(f"/api/v1/plans/{plan.id}", json=body).status_code == 200


def test_wrong_encryption_key_prevents_startup(settings, sessions, source):
    from fastapi.testclient import TestClient
    from pydantic import SecretStr

    from bootstrap.rest import create_app

    settings.CRYPT_KEY = SecretStr(Fernet.generate_key().decode())
    with (
        pytest.raises(ValueError, match="Cannot decrypt"),
        TestClient(create_app(settings)),
    ):
        pass
