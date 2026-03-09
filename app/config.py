"""
Application configuration loaded from environment variables.

Maps to the C4 'Platform API' container settings.
"""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """All configuration is loaded from environment variables or a .env file."""

    # ── Database (Platform DB + Registry DB — shared PostgreSQL) ─────────
    database_url: str = (
        "postgresql+asyncpg://comfortos:comfortos@localhost:5432/comfortos"
    )

    # ── JWT / Identity Provider ──────────────────────────────────────────
    secret_key: str = "CHANGE-ME-IN-PRODUCTION"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7
    google_oauth_client_id: str | None = (
        "173455945512-f2ba6o8fhrbdrmbqiqlqskuisobuttun.apps.googleusercontent.com"
    )

    # ── CORS ─────────────────────────────────────────────────────────────
    cors_origins: str = "*"

    # ── Rate limiting ────────────────────────────────────────────────────
    rate_limit_requests: int = 100
    rate_limit_window_seconds: int = 60

    # ── Connector Gateway ────────────────────────────────────────────────
    connector_gateway_timeout_seconds: int = 15

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


settings = Settings()
