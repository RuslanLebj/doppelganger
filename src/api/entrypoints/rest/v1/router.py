from fastapi import APIRouter, Depends

from api.entrypoints.rest.v1.routes import plan_router, run_router, target_router
from api.security import check_api_key

api_v1_router = APIRouter(prefix="/api/v1", dependencies=[Depends(check_api_key)])
api_v1_router.include_router(target_router)
api_v1_router.include_router(plan_router)
api_v1_router.include_router(run_router)
