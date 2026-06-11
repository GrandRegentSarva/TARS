"""
Phase 5 Configuration
=====================
Environment-based settings for the Gemini Reasoning Layer.

Reads from environment variables (or .env file via python-dotenv).
All settings have sensible defaults for local development.
"""

from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()


class Settings:
    """Phase 5 configuration loaded from environment variables."""

    # Redis connection URL (reuses shared Redis instance)
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")

    # Phase 4 Incident API base URL
    PHASE4_API_URL: str = os.getenv("PHASE4_API_URL", "http://localhost:8003")

    # Reasoning API server
    REASONING_API_HOST: str = os.getenv("REASONING_API_HOST", "0.0.0.0")
    REASONING_API_PORT: int = int(os.getenv("REASONING_API_PORT", "8004"))

    # Redis key prefix
    REDIS_KEY_PREFIX: str = "tars:mission"

    # HTTP client timeout for Phase 4 API calls (seconds)
    INCIDENT_CLIENT_TIMEOUT: float = float(
        os.getenv("INCIDENT_CLIENT_TIMEOUT", "30.0")
    )

    # Gemini configuration
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    GEMINI_TEMPERATURE: float = float(os.getenv("GEMINI_TEMPERATURE", "0.1"))


settings = Settings()
