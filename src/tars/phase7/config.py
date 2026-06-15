"""
Phase 7 Configuration
=====================
Environment-based settings for the Neo4j Operational Memory service.

Reads from environment variables (or .env file via python-dotenv).
All settings have sensible defaults for local development.
"""

from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()


class Settings:
    """Phase 7 configuration loaded from environment variables."""

    # Neo4j connection
    NEO4J_URI: str = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    NEO4J_USER: str = os.getenv("NEO4J_USER", "neo4j")
    NEO4J_PASSWORD: str = os.getenv("NEO4J_PASSWORD", "")
    NEO4J_DATABASE: str = os.getenv("NEO4J_DATABASE", "neo4j")

    # Memory API server
    MEMORY_API_HOST: str = os.getenv("MEMORY_API_HOST", "0.0.0.0")
    MEMORY_API_PORT: int = int(os.getenv("MEMORY_API_PORT", "8005"))

    # Upstream API URLs
    PHASE2_API_URL: str = os.getenv("PHASE2_API_URL", "http://localhost:8000")
    PHASE4_API_URL: str = os.getenv("PHASE4_API_URL", "http://localhost:8003")
    PHASE5_API_URL: str = os.getenv("PHASE5_API_URL", "http://localhost:8004")

    # HTTP client timeout for upstream API calls (seconds)
    MEMORY_CLIENT_TIMEOUT: float = float(
        os.getenv("MEMORY_CLIENT_TIMEOUT", "30.0")
    )

    # Query limits
    MEMORY_QUERY_DEFAULT_LIMIT: int = int(
        os.getenv("MEMORY_QUERY_DEFAULT_LIMIT", "20")
    )
    MEMORY_QUERY_MAX_LIMIT: int = int(
        os.getenv("MEMORY_QUERY_MAX_LIMIT", "100")
    )


settings = Settings()
