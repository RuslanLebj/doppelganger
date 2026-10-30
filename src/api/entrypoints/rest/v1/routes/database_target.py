from fastapi import APIRouter

from api.entrypoints.rest.v1.deps import BackupServiceDep
from app.application.schemas.backup import PasswordChange, TargetCreate, TargetRead

target_router = APIRouter(prefix="/targets", tags=["Database targets"])


@target_router.get("", response_model=list[TargetRead])
def targets(service: BackupServiceDep):
    return service.targets()


@target_router.post("", response_model=TargetRead, status_code=201)
def create_target(body: TargetCreate, service: BackupServiceDep):
    return service.save_target(body)


@target_router.put("/{target_id}", response_model=TargetRead)
def update_target(target_id: int, body: TargetCreate, service: BackupServiceDep):
    return service.save_target(body, target_id)


@target_router.put("/{target_id}/password", status_code=204)
def change_password(target_id: int, body: PasswordChange, service: BackupServiceDep):
    service.change_password(target_id, body.password.get_secret_value())
