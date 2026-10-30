from datetime import UTC, datetime
from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from apscheduler.triggers.cron import CronTrigger
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

Name = Annotated[str, Field(min_length=1, max_length=100, pattern=r"^[\w .-]+$")]
Identifier = Annotated[
    str, Field(min_length=1, max_length=63, pattern=r"^[A-Za-z0-9_][A-Za-z0-9_.-]*$")
]
SslMode = Literal["verify-full", "verify-ca", "require", "disable"]


class TargetCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Name
    host: str = Field(min_length=1, max_length=253, pattern=r"^[A-Za-z0-9_.:\-]+$")
    port: int = Field(default=5432, ge=1, le=65535)
    database: Identifier
    username: Identifier
    password: SecretStr
    sslmode: SslMode = "verify-full"

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: SecretStr) -> SecretStr:
        password = value.get_secret_value()
        if not password or any(char in password for char in "\r\n\x00"):
            raise ValueError(
                "Password must be nonempty and contain no line breaks or NUL"
            )
        return value


class TargetRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    host: str
    port: int
    database: str
    username: str
    sslmode: str


class PasswordChange(BaseModel):
    password: SecretStr

    _validate_password = field_validator("password")(
        TargetCreate.validate_password.__func__
    )


class PlanCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Name
    target_id: int = Field(gt=0)
    cron: str = "0 2 * * *"
    timezone: str = "Asia/Yekaterinburg"
    enabled: bool = False
    max_dump_seconds: int = Field(default=7200, ge=60, le=86400)
    lock_wait_seconds: int = Field(default=5, ge=1, le=60)

    @field_validator("cron")
    @classmethod
    def validate_cron(cls, value: str) -> str:
        fields = value.split()
        # MVP explicitly supports one daily run, not arbitrary high-frequency jobs.
        if len(fields) != 5 or fields[2:] != ["*", "*", "*"]:
            raise ValueError("Use a daily cron expression: minute hour * * *")
        if not fields[0].isdigit() or not fields[1].isdigit():
            raise ValueError("Daily hour and minute must be single numbers")
        CronTrigger.from_crontab(value)
        return value

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError, ValueError:
            raise ValueError("Unknown IANA timezone") from None
        return value


class UTCOutput(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    @field_validator("*", mode="after")
    @classmethod
    def attach_utc(cls, value):
        if isinstance(value, datetime) and value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value


class PlanRead(UTCOutput):
    id: int
    name: str
    target_id: int
    cron: str
    timezone: str
    enabled: bool
    max_dump_seconds: int
    lock_wait_seconds: int
    next_run_at: datetime | None


class RunRead(UTCOutput):
    id: int
    plan_id: int
    status: str
    trigger: str
    dump_path: str | None
    s3_key: str | None
    s3_status: str
    dump_bytes: int | None
    error: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
