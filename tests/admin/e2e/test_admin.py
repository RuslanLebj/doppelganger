import re

from app.infrastructure.db.models import BackupPlan, DatabaseTarget
from utils.cryptography.fernet import SecretCipher


def login(client):
    page = client.get("/admin/login")
    token = re.search(r'name="csrf" value="([^"]+)"', page.text).group(1)
    response = client.post(
        "/admin/login",
        data={"username": "test-admin", "password": "test-admin-password", "csrf": token},
        follow_redirects=False,
    )
    assert response.status_code == 303
    page = client.get("/admin/")
    assert page.status_code == 200
    return re.search(r'name="csrf-token" content="([^"]+)"', page.text).group(1)


def test_admin_requires_login_and_does_not_accept_api_key(client):
    response = client.get("/admin/", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/admin/login"
    assert client.post("/admin/plans/1/runs").status_code == 401
    page = client.get("/admin/login")
    token = re.search(r'name="csrf" value="([^"]+)"', page.text).group(1)
    response = client.post(
        "/admin/login",
        data={
            "username": "test-admin",
            "password": "wrong-sensitive-value",
            "csrf": token,
        },
    )
    assert response.status_code == 401
    assert "Неверный логин или пароль" in response.text
    assert "wrong-sensitive-value" not in response.text


def test_admin_creates_targets_and_daily_cron_without_exposing_passwords(
    client, sessions, settings
):
    token = login(client)
    headers = {"X-CSRF-Token": token}
    body = {
        "name": "admin-database",
        "host": "source.test",
        "database": "source",
        "username": "backup",
        "password": "private-db-password",
    }
    assert client.post("/admin/targets", json=body).status_code == 403
    response = client.post("/admin/targets", json=body, headers=headers)
    assert response.status_code == 200
    target_id = response.json()["id"]
    assert "password" not in response.text
    plan = {
        "name": "admin-nightly",
        "target_id": target_id,
        "cron": "0 2 * * *",
        "timezone": "Asia/Yekaterinburg",
        "enabled": False,
    }
    invalid = client.post(
        "/admin/plans", json=plan | {"cron": "* * * * *"}, headers=headers
    )
    assert invalid.status_code == 422
    response = client.post("/admin/plans", json=plan, headers=headers)
    assert response.status_code == 200
    plan_id = response.json()["id"]
    response = client.put(
        f"/admin/plans/{plan_id}",
        json=plan | {"cron": "15 3 * * *", "enabled": True},
        headers=headers,
    )
    assert response.status_code == 200
    assert response.json()["next_run_at"].endswith("Z")
    assert client.get("/api/v1/plans").json()[0]["cron"] == "15 3 * * *"
    page = client.get("/admin/").text
    assert "private-db-password" not in page
    assert settings.API_KEY.get_secret_value() not in page
    assert settings.CRYPT_KEY.get_secret_value() not in page
    with sessions() as session:
        target = session.get(DatabaseTarget, target_id)
        assert target.password_encrypted not in page
        assert (
            SecretCipher(settings.CRYPT_KEY.get_secret_value()).decrypt(
                target.password_encrypted
            )
            == "private-db-password"
        )
        assert session.get(BackupPlan, plan_id).enabled is True


def test_admin_edit_keeps_existing_password_and_logout_revokes_access(
    client, sessions, settings, source
):
    token = login(client)
    target, _ = source
    body = {
        "name": target.name,
        "host": "new-source.test",
        "port": target.port,
        "database": target.database,
        "username": target.username,
        "sslmode": target.sslmode,
    }
    with sessions() as session:
        original = SecretCipher(settings.CRYPT_KEY.get_secret_value()).decrypt(
            session.get(DatabaseTarget, target.id).password_encrypted
        )
    response = client.put(
        f"/admin/targets/{target.id}", json=body, headers={"X-CSRF-Token": token}
    )
    assert response.status_code == 200
    with sessions() as session:
        updated = session.get(DatabaseTarget, target.id)
        assert updated.host == "new-source.test"
        assert (
            SecretCipher(settings.CRYPT_KEY.get_secret_value()).decrypt(
                updated.password_encrypted
            )
            == original
        )
    assert (
        client.post("/admin/logout", headers={"X-CSRF-Token": token}).status_code == 200
    )
    assert (
        client.post(
            f"/admin/plans/{source[1].id}/runs", headers={"X-CSRF-Token": token}
        ).status_code
        == 401
    )


def test_admin_cannot_login_without_configured_credentials(client, settings):
    settings.ADMIN_PASSWORD = None
    page = client.get("/admin/login")
    token = re.search(r'name="csrf" value="([^"]+)"', page.text).group(1)
    response = client.post(
        "/admin/login", data={"username": "test-admin", "password": "", "csrf": token}
    )
    assert response.status_code == 401
    assert client.get("/admin/", follow_redirects=False).status_code == 303
