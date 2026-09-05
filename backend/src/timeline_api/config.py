from enum import StrEnum

from pydantic import AnyHttpUrl, Field, MongoDsn, PostgresDsn
from pydantic_settings import BaseSettings, SettingsConfigDict


class LogLevel(StrEnum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="TIMELINE_",
        extra="ignore",
        frozen=True,
    )

    app_name: str = "Federated Patient Timeline API"
    app_version: str = "0.1.0"
    postgres_dsn: PostgresDsn = PostgresDsn(
        "postgresql://postgres:postgres@localhost:5432/registry"
    )
    mongo_uri: MongoDsn = MongoDsn("mongodb://localhost:27017")
    mongo_database: str = "pacs"
    vitals_base_url: AnyHttpUrl = AnyHttpUrl("http://localhost:3001")
    log_level: LogLevel = LogLevel.INFO
    postgres_pool_max_size: int = Field(default=10, ge=1)
