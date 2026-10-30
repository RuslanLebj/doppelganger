from fastapi import APIRouter

from api.entrypoints.rest.v1.deps import BackupServiceDep
from app.application.schemas.backup import PlanCreate, PlanRead, RunRead

plan_router = APIRouter(prefix="/plans", tags=["Backup plans"])


@plan_router.get("", response_model=list[PlanRead])
def plans(service: BackupServiceDep):
    return service.plans()


@plan_router.post("", response_model=PlanRead, status_code=201)
def create_plan(body: PlanCreate, service: BackupServiceDep):
    return service.save_plan(body)


@plan_router.put("/{plan_id}", response_model=PlanRead)
def update_plan(plan_id: int, body: PlanCreate, service: BackupServiceDep):
    return service.save_plan(body, plan_id)


@plan_router.post("/{plan_id}/runs", response_model=RunRead, status_code=202)
def enqueue(plan_id: int, service: BackupServiceDep):
    return service.enqueue(plan_id)
