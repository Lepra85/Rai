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

    # Shared secret used to authenticate flow → /resolve, /op webhook calls.
    flow_api_secret: str = ""

    # Kapso platform API key — used to send outbound WhatsApp messages via
    # https://api.kapso.ai/meta/whatsapp/...
    kapso_api_key: str = ""

    # Kapso webhook signing secret — Kapso signs every inbound webhook with
    # HMAC-SHA256(this_secret, raw_body) and sends the hex digest in
    # X-Webhook-Signature. Empty → /webhook/whatsapp rejects everything.
    kapso_webhook_secret: str = ""

    # Default WhatsApp Business phone_number_id used for outbound sends when
    # the caller doesn't override. Multi-tenant code typically passes one
    # explicitly per empresa. This is an optional default for single-tenant
    # local testing.
    whatsapp_default_phone_number_id: str = ""


def get_settings() -> Settings:
    return Settings()
