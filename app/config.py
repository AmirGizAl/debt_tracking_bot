import logging
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class DatabaseSettings(BaseSettings):
    """The part of the configuration that Alembic needs (no bot token required)."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str


class Settings(DatabaseSettings):
    bot_token: SecretStr
    owner_telegram_id: int
    redis_url: str | None = None
    tz: str = "Europe/Moscow"  # the customer works in Moscow time
    log_level: str = "INFO"
    proxy_url: str | None = None

    @field_validator("redis_url", "proxy_url", mode="before")
    @classmethod
    def _empty_to_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("owner_telegram_id")
    @classmethod
    def _check_owner_id(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("OWNER_TELEGRAM_ID must be a positive Telegram user id")
        return value

    @field_validator("tz")
    @classmethod
    def _check_tz(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"Unknown time zone: {value!r}") from exc
        return value

    @field_validator("log_level")
    @classmethod
    def _check_log_level(cls, value: str) -> str:
        level = value.strip().upper()
        if level not in logging.getLevelNamesMapping():
            raise ValueError(f"Unknown log level: {value!r}")
        return level

    @property
    def zone(self) -> ZoneInfo:
        return ZoneInfo(self.tz)
