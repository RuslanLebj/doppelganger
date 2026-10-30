from hashlib import sha256
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from config import Settings

ADMIN_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(ADMIN_DIR / "templates"))
templates.env.globals["static_versions"] = {
    path.name: sha256(path.read_bytes()).hexdigest()[:12]
    for path in (ADMIN_DIR / "static").iterdir()
    if path.is_file()
}


def setup_admin(app: FastAPI, settings: Settings):
    from admin.views.backup import admin_router, login_router

    # Unconfigured admin credentials never grant access, even with a forged cookie.
    secret = settings.ADMIN_SESSION_SECRET_KEY
    app.add_middleware(
        SessionMiddleware,
        secret_key=secret.get_secret_value() if secret else "admin-not-configured",
        session_cookie="doppelganger_admin",
        path="/admin",
        max_age=8 * 60 * 60,
        same_site="strict",
        https_only=settings.ADMIN_COOKIE_SECURE,
    )
    app.mount(
        "/admin/static", StaticFiles(directory=ADMIN_DIR / "static"), name="admin-static"
    )
    app.include_router(login_router)
    app.include_router(admin_router)
