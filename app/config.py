"""
Application configuration loaded from environment variables.

Maps to the C4 'Platform API' container settings.
"""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """All configuration is loaded from environment variables or a .env file."""

    # ── Database (Supabase PostgreSQL) ──────────────────────────────────
    database_url: str = (
        "postgresql+asyncpg://postgres:postgres@localhost:5432/postgres"
    )

    # ── Firebase Authentication ──────────────────────────────────────────
    firebase_service_account_key_path: str = "firebase-service-account.json"
    firebase_project_id: str = "comfortos"

    # ── CORS ─────────────────────────────────────────────────────────────
    cors_origins: str = (
        "http://localhost:3000,"
        "http://127.0.0.1:3000,"
        "http://localhost:5173,"
        "http://127.0.0.1:5173,"
        "http://localhost:8000,"
        "http://127.0.0.1:8000,"
        "https://comfortos.netlify.app,"
        "https://api.scientify.in"
    )

    # ── Database Pool (small VM — keep connections minimal) ──────────────
    db_pool_size: int = 3
    db_max_overflow: int = 5

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
