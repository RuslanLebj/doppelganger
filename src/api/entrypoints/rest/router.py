from fastapi import APIRouter

from .healthcheck import healthcheck_router
from .v1.router import api_v1_router

main_router = APIRouter()
main_router.include_router(healthcheck_router)
main_router.include_router(api_v1_router)
