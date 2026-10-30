from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.application.services.backup import BackupService
from db.postgresql.session import get_db_session

DBSessionDep = Annotated[Session, Depends(get_db_session)]


def get_backup_service(session: DBSessionDep, request: Request) -> BackupService:
    return BackupService(session, request.app.state.settings, request.app.state.cipher)


BackupServiceDep = Annotated[BackupService, Depends(get_backup_service)]
