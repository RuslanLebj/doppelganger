import secrets

from fastapi import HTTPException, Request


def is_configured(request: Request) -> bool:
    settings = request.app.state.settings
    return bool(settings.ADMIN_PASSWORD and settings.ADMIN_SESSION_SECRET_KEY)


def csrf_token(request: Request) -> str:
    if "csrf" not in request.session:
        request.session["csrf"] = secrets.token_urlsafe(32)
    return request.session["csrf"]


def check_csrf(request: Request, supplied: str | None):
    expected = request.session.get("csrf")
    if not expected or not supplied or not secrets.compare_digest(expected, supplied):
        raise HTTPException(403, "Обновите страницу и повторите действие")


def require_admin(request: Request):
    settings = request.app.state.settings
    if (
        not is_configured(request)
        or request.session.get("admin_user") != settings.ADMIN_USERNAME
    ):
        if request.method == "GET":
            raise HTTPException(303, headers={"Location": "/admin/login"})
        raise HTTPException(401, "Войдите в админку")
    if request.method not in {"GET", "HEAD"}:
        check_csrf(request, request.headers.get("X-CSRF-Token"))
