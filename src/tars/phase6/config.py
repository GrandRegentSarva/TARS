"""
Phase 6 Configuration
=====================
Environment-based settings for Phoenix tracing and observability.

Reads from environment variables (or .env file via python-dotenv).
All settings have sensible defaults that keep tracing disabled.

Content modes:
- ``full``: Capture bounded prompt and structured response.
- ``metadata``: Capture identifiers, model, timing, outcome only.
- ``disabled``: Do not initialize tracing or export spans.
"""

from __future__ import annotations

import logging
import os
from enum import Enum
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("phase6.config")


class ContentMode(str, Enum):
    """Trace content capture policy."""

    FULL = "full"
    METADATA = "metadata"
    DISABLED = "disabled"


class PhoenixSettings:
    """Phase 6 Phoenix and tracing configuration."""

    # Master switch — tracing is disabled by default
    ENABLED: bool = os.getenv("PHOENIX_ENABLED", "false").lower() in (
        "true",
        "1",
        "yes",
    )

    # Phoenix OTLP endpoint
    ENDPOINT: str = os.getenv(
        "PHOENIX_ENDPOINT", "http://localhost:6006"
    )

    # Phoenix project name (appears in the Phoenix UI)
    PROJECT_NAME: str = os.getenv(
        "PHOENIX_PROJECT_NAME", "tars-phase5-reasoning"
    )

    # Content capture mode
    CONTENT_MODE: ContentMode = ContentMode.FULL

    # OTLP export timeout in seconds
    EXPORT_TIMEOUT_SECONDS: float = 5.0

    # Whether to use batch span export (recommended for production)
    BATCH_EXPORT: bool = True

    def __init__(self) -> None:
        # Parse content mode with safe fallback
        raw_mode = os.getenv("PHOENIX_CONTENT_MODE", "full").lower()
        try:
            self.CONTENT_MODE = ContentMode(raw_mode)
        except ValueError:
            logger.warning(
                "Invalid PHOENIX_CONTENT_MODE '%s'; falling back to 'full'",
                raw_mode,
            )
            self.CONTENT_MODE = ContentMode.FULL

        # Parse export timeout
        try:
            self.EXPORT_TIMEOUT_SECONDS = float(
                os.getenv("PHOENIX_EXPORT_TIMEOUT_SECONDS", "5.0")
            )
        except (ValueError, TypeError):
            logger.warning(
                "Invalid PHOENIX_EXPORT_TIMEOUT_SECONDS; using default 5.0"
            )
            self.EXPORT_TIMEOUT_SECONDS = 5.0

        # Parse batch export flag
        self.BATCH_EXPORT = os.getenv(
            "PHOENIX_BATCH_EXPORT", "true"
        ).lower() in ("true", "1", "yes")

        # Re-read enabled flag (instance-level for testability)
        self.ENABLED = os.getenv("PHOENIX_ENABLED", "false").lower() in (
            "true",
            "1",
            "yes",
        )

        # Re-read endpoint and project name
        self.ENDPOINT = os.getenv(
            "PHOENIX_ENDPOINT", "http://localhost:6006"
        )
        self.PROJECT_NAME = os.getenv(
            "PHOENIX_PROJECT_NAME", "tars-phase5-reasoning"
        )

    @property
    def is_tracing_enabled(self) -> bool:
        """Return True if tracing should be initialized."""
        return self.ENABLED and self.CONTENT_MODE != ContentMode.DISABLED

    @property
    def capture_content(self) -> bool:
        """Return True if prompt/response bodies should be captured."""
        return self.CONTENT_MODE == ContentMode.FULL

    @property
    def otlp_endpoint(self) -> str:
        """Return the OTLP traces endpoint for Phoenix."""
        endpoint = self.ENDPOINT.rstrip("/")
        # Phoenix expects traces at /v1/traces
        if not endpoint.endswith("/v1/traces"):
            endpoint = f"{endpoint}/v1/traces"
        return endpoint


phoenix_settings = PhoenixSettings()
