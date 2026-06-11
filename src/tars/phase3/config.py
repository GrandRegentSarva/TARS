"""
Phase 3 Configuration
=====================
Environment-based settings for the State Engine.

Reads from environment variables (or .env file via python-dotenv).
All settings have sensible defaults for local development.
"""

from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()


class Settings:
    """Phase 3 configuration loaded from environment variables."""

    # Redis connection URL
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")

    # Phase 2 Replay API base URL
    PHASE2_API_URL: str = os.getenv("PHASE2_API_URL", "http://localhost:8000")

    # State Engine API server
    STATE_API_HOST: str = os.getenv("STATE_API_HOST", "0.0.0.0")
    STATE_API_PORT: int = int(os.getenv("STATE_API_PORT", "8002"))

    # Redis key prefix
    REDIS_KEY_PREFIX: str = "tars:mission"

    # HTTP client timeout for Phase 2 API calls (seconds)
    REPLAY_CLIENT_TIMEOUT: float = float(os.getenv("REPLAY_CLIENT_TIMEOUT", "30.0"))


settings = Settings()
