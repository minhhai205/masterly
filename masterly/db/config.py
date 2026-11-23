"""Database connection settings, read from the environment or the project ``.env``.

Only the password is a secret. The backend builds the connection URL itself so
each part can come from its own variable (on AWS, from the RDS secret's fields).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class DatabaseSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="DB_",
        env_file=PROJECT_ROOT / ".env",
        extra="ignore",
    )

    host: str = "localhost"
    port: int = 5432
    name: str = "masterly"
    user: str = "masterly"
    password: SecretStr = SecretStr("")

    def url(self, database: str | None = None) -> URL:
        return URL.create(
            "postgresql+asyncpg",
            username=self.user,
            password=self.password.get_secret_value() or None,
            host=self.host,
            port=self.port,
            database=database or self.name,
        )


@lru_cache(maxsize=1)
def get_database_settings() -> DatabaseSettings:
    return DatabaseSettings()
