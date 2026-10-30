from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.db.models.base import BaseModel, utcnow


class BackupPlan(BaseModel):
    __tablename__ = "backup_plan"
    __table_args__ = (CheckConstraint("max_dump_seconds > 0"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    target_id: Mapped[int] = mapped_column(ForeignKey("database_target.id"))
    cron: Mapped[str] = mapped_column(String(100), default="0 2 * * *")
    timezone: Mapped[str] = mapped_column(String(100), default="Asia/Yekaterinburg")
    enabled: Mapped[bool] = mapped_column(default=False)
    max_dump_seconds: Mapped[int] = mapped_column(default=7200)
    lock_wait_seconds: Mapped[int] = mapped_column(default=5)
    next_run_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
