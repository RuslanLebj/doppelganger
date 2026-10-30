import secrets
from datetime import timedelta

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from pydantic import SecretStr, field_validator
from sqlalchemy import func, select

from admin.auth.auth import check_csrf, csrf_token, is_configured, require_admin
from admin.setup import templates
from api.entrypoints.rest.v1.deps import BackupServiceDep, DBSessionDep
from app.application.schemas.backup import (
    PlanCreate,
    PlanRead,
    RunRead,
    TargetCreate,
    TargetRead,
)
from app.infrastructure.db.models import BackupRun
from app.infrastructure.db.models.base import utcnow

login_router = APIRouter(prefix="/admin", include_in_schema=False)
admin_router = APIRouter(
    prefix="/admin", include_in_schema=False, dependencies=[Depends(require_admin)]
)


@login_router.get("/login")
def login_page(request: Request):
    return templates.TemplateResponse(
        request,
        "login.html",
        {
            "csrf": csrf_token(request),
            "configured": is_configured(request),
            "error": None,
        },
    )


@login_router.post("/login")
async def login(request: Request):
    form = await request.form()
    check_csrf(request, form.get("csrf"))
    settings = request.app.state.settings
    valid_user = secrets.compare_digest(
        str(form.get("username", "")).encode(), settings.ADMIN_USERNAME.encode()
    )
    valid_password = secrets.compare_digest(
        str(form.get("password", "")).encode(),
        settings.ADMIN_PASSWORD.get_secret_value().encode()
        if settings.ADMIN_PASSWORD
        else b"",
    )
    if not is_configured(request) or not (valid_user and valid_password):
        return templates.TemplateResponse(
            request,
            "login.html",
            {
                "csrf": csrf_token(request),
                "configured": is_configured(request),
                "error": "Неверный логин или пароль"
                if is_configured(request)
                else "Вход ещё не настроен. Обратитесь к администратору сервиса.",
            },
            status_code=401,
        )
    request.session.clear()
    request.session["admin_user"] = settings.ADMIN_USERNAME
    csrf_token(request)
    return RedirectResponse("/admin/", status_code=303)


@admin_router.post("/logout")
def logout(request: Request):
    request.session.clear()
    return {"ok": True}


@admin_router.get("/")
def dashboard(request: Request, service: BackupServiceDep, session: DBSessionDep):
    targets = service.targets()
    plans = service.plans()
    runs = service.runs(None, 100, 0)
    counts = dict(
        session.execute(
            select(BackupRun.status, func.count(BackupRun.id))
            .where(BackupRun.created_at >= utcnow() - timedelta(days=1))
            .group_by(BackupRun.status)
        ).all()
    )
    data = {
        "targets": [
            TargetRead.model_validate(item).model_dump(mode="json") for item in targets
        ],
        "plans": [
            PlanRead.model_validate(item).model_dump(mode="json") for item in plans
        ],
        "runs": [RunRead.model_validate(item).model_dump(mode="json") for item in runs],
        "execution_enabled": service.settings.BACKUP_EXECUTION_ENABLED,
        "retention_days": service.settings.RETENTION_DAYS,
        "counts": counts,
    }
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "csrf": csrf_token(request),
            "data": data,
            "username": request.session["admin_user"],
        },
    )


@admin_router.post("/targets", response_model=TargetRead)
def create_target(body: TargetCreate, service: BackupServiceDep):
    return service.save_target(body)


class TargetUpdate(TargetCreate):
    password: SecretStr | None = None

    @field_validator("password")
    @classmethod
    def validate_password(cls, value):
        return TargetCreate.validate_password(value) if value is not None else None


@admin_router.put("/targets/{target_id}", response_model=TargetRead)
def update_target(target_id: int, body: TargetUpdate, service: BackupServiceDep):
    if body.password is None:
        target = service.target_details(target_id)
        body = body.model_copy(
            update={
                "password": SecretStr(service.cipher.decrypt(target.password_encrypted))
            }
        )
    return service.save_target(body, target_id)


@admin_router.post("/plans", response_model=PlanRead)
def create_plan(body: PlanCreate, service: BackupServiceDep):
    return service.save_plan(body)


@admin_router.put("/plans/{plan_id}", response_model=PlanRead)
def update_plan(plan_id: int, body: PlanCreate, service: BackupServiceDep):
    return service.save_plan(body, plan_id)


@admin_router.post("/plans/{plan_id}/runs", response_model=RunRead, status_code=202)
def enqueue(plan_id: int, service: BackupServiceDep):
    return service.enqueue(plan_id)


@admin_router.post("/runs/{run_id}/retry", response_model=RunRead, status_code=202)
def retry(run_id: int, service: BackupServiceDep):
    return service.retry_s3(run_id)
