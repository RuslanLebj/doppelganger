from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from api.entrypoints.rest.v1.deps import DBSessionDep

healthcheck_router = APIRouter(
    prefix="/healthcheck", tags=["Health check"], include_in_schema=False
)


@healthcheck_router.get("/")
def app_health_check():
    return {"success": True, "msg": "App available"}


@healthcheck_router.get("/db")
def db_health_check(session: DBSessionDep):
    try:
        session.execute(text("SELECT 1"))
    except SQLAlchemyError:
        return JSONResponse(
            status_code=503, content={"success": False, "msg": "DB unavailable"}
        )
    return {"success": True, "msg": "DB available"}
