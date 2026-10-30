from fastapi import APIRouter, Query

from api.entrypoints.rest.v1.deps import BackupServiceDep
from app.application.schemas.backup import RunRead

run_router = APIRouter(prefix="/runs", tags=["Backup runs"])


@run_router.get("", response_model=list[RunRead])
def runs(
    service: BackupServiceDep,
    plan_id: int | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    return service.runs(plan_id, limit, offset)


@run_router.get("/{run_id}", response_model=RunRead)
def run_details(run_id: int, service: BackupServiceDep):
    return service.run_details(run_id)


@run_router.post("/{run_id}/retry-s3", response_model=RunRead, status_code=202)
def retry_s3(run_id: int, service: BackupServiceDep):
    return service.retry_s3(run_id)
