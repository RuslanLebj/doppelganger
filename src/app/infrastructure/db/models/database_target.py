from datetime import datetime

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.db.models.base import BaseModel, utcnow


class DatabaseTarget(BaseModel):
    __tablename__ = "database_target"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    host: Mapped[str] = mapped_column(String(253))
    port: Mapped[int] = mapped_column(default=5432)
    database: Mapped[str] = mapped_column(String(63))
    username: Mapped[str] = mapped_column(String(63))
    password_encrypted: Mapped[str] = mapped_column(Text)
    sslmode: Mapped[str] = mapped_column(String(20), default="verify-full")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
