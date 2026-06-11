"""
Phase 4 Configuration
=====================
Environment-based settings for the Incident Engine.

Reads from environment variables (or .env file via python-dotenv).
All settings have sensible defaults for local development.
"""

from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()


class Settings:
    """Phase 4 configuration loaded from environment variables."""

    # Redis connection URL (reuses Phase 3 Redis instance)
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")

    # Phase 3 State API base URL
    PHASE3_API_URL: str = os.getenv("PHASE3_API_URL", "http://localhost:8002")

    # Incident Engine API server
    INCIDENT_API_HOST: str = os.getenv("INCIDENT_API_HOST", "0.0.0.0")
    INCIDENT_API_PORT: int = int(os.getenv("INCIDENT_API_PORT", "8003"))

    # Redis key prefix
    REDIS_KEY_PREFIX: str = "tars:mission"

    # HTTP client timeout for Phase 3 API calls (seconds)
    STATE_CLIENT_TIMEOUT: float = float(os.getenv("STATE_CLIENT_TIMEOUT", "30.0"))

    # Incident detection thresholds
    INCIDENT_MAX_GAP_MS: int = int(os.getenv("INCIDENT_MAX_GAP_MS", "5000"))
    INCIDENT_MIN_STATES: int = int(os.getenv("INCIDENT_MIN_STATES", "3"))
    INCIDENT_HIGH_RISK: float = float(os.getenv("INCIDENT_HIGH_RISK", "0.8"))
    INCIDENT_ELEVATED_RISK: float = float(os.getenv("INCIDENT_ELEVATED_RISK", "0.6"))


settings = Settings()
