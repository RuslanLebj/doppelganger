from sqlalchemy import URL, create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from config import Settings


def make_engine(settings: Settings) -> Engine:
    if settings.POSTGRES_DB_PASSWORD is None:
        raise ValueError("POSTGRES_DB_PASSWORD is required")
    url = URL.create(
        "postgresql+psycopg",
        username=settings.POSTGRES_DB_USER,
        password=settings.POSTGRES_DB_PASSWORD.get_secret_value(),
        host=settings.POSTGRES_DB_HOST,
        port=settings.POSTGRES_DB_PORT,
        database=settings.POSTGRES_DB_NAME,
        query={"sslmode": settings.POSTGRES_SSLMODE, "connect_timeout": "10"},
    )
    return create_engine(
        url,
        pool_size=settings.POSTGRES_POOL_MIN_SIZE,
        max_overflow=settings.POSTGRES_POOL_MAX_SIZE - settings.POSTGRES_POOL_MIN_SIZE,
        pool_pre_ping=True,
        hide_parameters=True,
    )


def make_session_factory(engine: Engine):
    return sessionmaker(engine, expire_on_commit=False)
