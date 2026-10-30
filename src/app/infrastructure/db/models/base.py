from datetime import UTC, datetime

from sqlalchemy.orm import DeclarativeBase


def utcnow() -> datetime:
    # Metadata timestamps are stored as UTC; API responses include the UTC offset.
    return datetime.now(UTC).replace(tzinfo=None)


class BaseModel(DeclarativeBase):
    pass
