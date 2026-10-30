from pathlib import Path
from typing import Self

from pydantic import (
    Field,
    HttpUrl,
    SecretStr,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[1] / ".env",
        case_sensitive=True,
        extra="ignore",
        hide_input_in_errors=True,
    )

    SERVICE_NAME: str = "doppelganger"
    DATA_DIR: Path = Path("data/app")
    CRYPT_KEY: SecretStr | None = None
    API_KEY: SecretStr | None = None

    ADMIN_USERNAME: str = "admin"
    ADMIN_PASSWORD: SecretStr | None = None
    ADMIN_SESSION_SECRET_KEY: SecretStr | None = None
    ADMIN_COOKIE_SECURE: bool = False

    POSTGRES_DB_HOST: str = "127.0.0.1"
    POSTGRES_DB_PORT: int = Field(default=55432, ge=1, le=65535)
    POSTGRES_DB_NAME: str = "doppelganger"
    POSTGRES_DB_USER: str = "doppelganger"
    POSTGRES_DB_PASSWORD: SecretStr | None = None
    POSTGRES_POOL_MIN_SIZE: int = Field(default=1, ge=1)
    POSTGRES_POOL_MAX_SIZE: int = Field(default=5, ge=1)
    POSTGRES_SSLMODE: str = "prefer"

    S3_ENDPOINT: HttpUrl = HttpUrl("http://127.0.0.1:9000")
    S3_BUCKET: str = Field(
        default="doppelganger",
        min_length=3,
        max_length=63,
        pattern=r"^[a-z0-9][a-z0-9.-]*[a-z0-9]$",
    )
    S3_PREFIX: str = "postgres-backups"
    S3_REGION: str = "us-east-1"
    S3_ACCESS_KEY: str = Field(default="doppelganger-local", min_length=1)
    S3_SECRET_KEY: SecretStr | None = None
    RETENTION_DAYS: int | None = Field(default=7, ge=1)

    BACKUP_EXECUTION_ENABLED: bool = False
    PG_DUMP_COMMAND: str = "pg_dump"
    DUMP_COMPRESSION_LEVEL: int = Field(default=1, ge=0, le=9)
    MIN_FREE_BYTES: int = Field(default=10 * 1024**3, ge=0)
    SCHEDULER_POLL_SECONDS: int = Field(default=5, ge=1, le=300)
    STORAGE_TIMEOUT_SECONDS: int = Field(default=14400, ge=1)

    @field_validator(
        "CRYPT_KEY",
        "API_KEY",
        "POSTGRES_DB_PASSWORD",
        "ADMIN_PASSWORD",
        "ADMIN_SESSION_SECRET_KEY",
        "S3_SECRET_KEY",
        mode="before",
    )
    @classmethod
    def empty_optional_setting(cls, value):
        return None if value == "" else value

    @field_validator("RETENTION_DAYS", mode="before")
    @classmethod
    def empty_retention(cls, value):
        return None if value in ("", "0", 0) else value

    @model_validator(mode="after")
    def validate_settings(self) -> Self:
        if self.POSTGRES_POOL_MAX_SIZE < self.POSTGRES_POOL_MIN_SIZE:
            raise ValueError("POSTGRES_POOL_MAX_SIZE must be >= POSTGRES_POOL_MIN_SIZE")
        if self.S3_ENDPOINT.username or self.S3_ENDPOINT.password:
            raise ValueError("Use S3_ACCESS_KEY and S3_SECRET_KEY for S3 credentials")
        return self

    @property
    def BACKUPS_DIR(self) -> Path:
        return self.DATA_DIR / "staging"
