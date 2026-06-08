"""
Phase 2 Configuration
=====================
Environment-based settings for the Mission Replay System.

Reads from environment variables (or .env file via python-dotenv).
All settings have sensible defaults for local development.
"""

from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()


class Settings:
    """Phase 2 configuration loaded from environment variables."""

    # PostgreSQL connection (async driver)
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        "postgresql+asyncpg://tars:tars@localhost:5432/tars",
    )

    # Synchronous URL for Alembic migrations (replaces asyncpg with psycopg2)
    @property
    def DATABASE_URL_SYNC(self) -> str:
        return self.DATABASE_URL.replace("+asyncpg", "")

    # FastAPI server
    API_HOST: str = os.getenv("API_HOST", "0.0.0.0")
    API_PORT: int = int(os.getenv("API_PORT", "8000"))

    # Phase 1 output directory (where mission JSON files live)
    OUTPUT_DIR: str = os.getenv("OUTPUT_DIR", "output")


settings = Settings()
