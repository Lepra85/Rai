"""Application settings loaded from environment / .env."""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Database. Empty string allowed so the app can be imported without a DB
    # (catalog tests, Alembic env in offline mode, etc.).
    database_url: str = ""

    # Shared secret used to authenticate webhook calls from the Kapso flow.
    flow_api_secret: str = ""

    # Kapso platform API key, used by the flow-deploy tooling.
    kapso_api_key: str = ""


def get_settings() -> Settings:
    return Settings()
