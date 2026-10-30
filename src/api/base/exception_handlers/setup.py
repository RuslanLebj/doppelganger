from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.application.errors.backup import BackupConflict, BackupNotFound


def setup_exception_handlers(app: FastAPI):
    @app.exception_handler(BackupNotFound)
    async def not_found(_: Request, error: BackupNotFound):
        return JSONResponse(status_code=404, content={"detail": str(error)})

    @app.exception_handler(BackupConflict)
    async def conflict(_: Request, error: BackupConflict):
        return JSONResponse(status_code=409, content={"detail": str(error)})

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, error: RequestValidationError):
        # The default response includes raw input, which can contain passwords.
        return JSONResponse(
            status_code=422,
            content={
                "detail": [
                    {"loc": item["loc"], "type": item["type"], "msg": item["msg"]}
                    for item in error.errors()
                ]
            },
        )
