"""
Phase 8 Configuration
=====================
Environment-based settings for Phoenix MCP self-introspection.

Reads from environment variables (or .env file via python-dotenv).
All settings default to disabled/safe values.

Content modes:
- ``metadata``: Default. Return identifiers, attributes, stage timing,
  and safe errors only.
- ``summary``: Return metadata plus bounded summaries generated from
  safe span fields.
- ``full_dev``: Local development only. May return bounded prompt/response
  snippets. Requires explicit opt-in via PHOENIX_MCP_ALLOW_FULL_DEV_CONTENT.
- ``disabled``: Disable MCP tool registration and trace queries.
"""

from __future__ import annotations

import logging
import os
from enum import Enum

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("phase8.config")


class MCPContentMode(str, Enum):
    """Trace content capture policy for Phoenix MCP."""

    METADATA = "metadata"
    SUMMARY = "summary"
    FULL_DEV = "full_dev"
    DISABLED = "disabled"


# Valid content modes for runtime validation
_VALID_MODES = {m.value for m in MCPContentMode}


class PhoenixMCPSettings:
    """Phase 8 Phoenix MCP configuration loaded from environment variables."""

    # Master switch -- disabled by default
    ENABLED: bool = False

    # Phoenix endpoint for trace queries
    ENDPOINT: str = "http://localhost:6006"

    # Query timeout in seconds (short because introspection is advisory)
    TIMEOUT_SECONDS: float = 5.0

    # Content mode -- metadata by default
    CONTENT_MODE: MCPContentMode = MCPContentMode.METADATA

    # Default and maximum result limits
    DEFAULT_LIMIT: int = 5
    MAX_LIMIT: int = 20

    # Maximum trace IDs for comparison
    MAX_TRACE_IDS: int = 10

    # Maximum characters in a summary string
    MAX_SUMMARY_CHARS: int = 2000

    # Allow full_dev content mode (must be explicitly enabled)
    ALLOW_FULL_DEV_CONTENT: bool = False

    def __init__(self) -> None:
        # Parse enabled flag
        self.ENABLED = os.getenv(
            "PHOENIX_MCP_ENABLED", "false"
        ).lower() in ("true", "1", "yes")

        # Parse endpoint
        self.ENDPOINT = os.getenv(
            "PHOENIX_MCP_ENDPOINT", "http://localhost:6006"
        )

        # Parse timeout
        try:
            self.TIMEOUT_SECONDS = float(
                os.getenv("PHOENIX_MCP_TIMEOUT_SECONDS", "5.0")
            )
            if self.TIMEOUT_SECONDS <= 0:
                logger.warning(
                    "PHOENIX_MCP_TIMEOUT_SECONDS must be positive; "
                    "using default 5.0"
                )
                self.TIMEOUT_SECONDS = 5.0
        except (ValueError, TypeError):
            logger.warning(
                "Invalid PHOENIX_MCP_TIMEOUT_SECONDS; using default 5.0"
            )
            self.TIMEOUT_SECONDS = 5.0

        # Parse content mode
        raw_mode = os.getenv("PHOENIX_MCP_CONTENT_MODE", "metadata").lower()
        if raw_mode not in _VALID_MODES:
            logger.warning(
                "Invalid PHOENIX_MCP_CONTENT_MODE '%s'; "
                "disabling MCP tool registration",
                raw_mode,
            )
            self.CONTENT_MODE = MCPContentMode.DISABLED
        else:
            self.CONTENT_MODE = MCPContentMode(raw_mode)

        # Parse default limit
        try:
            self.DEFAULT_LIMIT = int(
                os.getenv("PHOENIX_MCP_DEFAULT_LIMIT", "5")
            )
            if self.DEFAULT_LIMIT < 1:
                self.DEFAULT_LIMIT = 1
        except (ValueError, TypeError):
            self.DEFAULT_LIMIT = 5

        # Parse max limit
        try:
            self.MAX_LIMIT = int(
                os.getenv("PHOENIX_MCP_MAX_LIMIT", "20")
            )
            if self.MAX_LIMIT < 1:
                self.MAX_LIMIT = 1
        except (ValueError, TypeError):
            self.MAX_LIMIT = 20

        # Ensure default <= max
        if self.DEFAULT_LIMIT > self.MAX_LIMIT:
            self.DEFAULT_LIMIT = self.MAX_LIMIT

        # Parse max trace IDs
        try:
            self.MAX_TRACE_IDS = int(
                os.getenv("PHOENIX_MCP_MAX_TRACE_IDS", "10")
            )
            if self.MAX_TRACE_IDS < 1:
                self.MAX_TRACE_IDS = 1
        except (ValueError, TypeError):
            self.MAX_TRACE_IDS = 10

        # Parse max summary chars
        try:
            self.MAX_SUMMARY_CHARS = int(
                os.getenv("PHOENIX_MCP_MAX_SUMMARY_CHARS", "2000")
            )
            if self.MAX_SUMMARY_CHARS < 100:
                self.MAX_SUMMARY_CHARS = 100
        except (ValueError, TypeError):
            self.MAX_SUMMARY_CHARS = 2000

        # Parse full_dev content allowance
        self.ALLOW_FULL_DEV_CONTENT = os.getenv(
            "PHOENIX_MCP_ALLOW_FULL_DEV_CONTENT", "false"
        ).lower() in ("true", "1", "yes")

        # Validate full_dev mode requires explicit opt-in
        if (
            self.CONTENT_MODE == MCPContentMode.FULL_DEV
            and not self.ALLOW_FULL_DEV_CONTENT
        ):
            logger.warning(
                "PHOENIX_MCP_CONTENT_MODE=full_dev requires "
                "PHOENIX_MCP_ALLOW_FULL_DEV_CONTENT=true; "
                "falling back to summary mode"
            )
            self.CONTENT_MODE = MCPContentMode.SUMMARY

    @property
    def is_enabled(self) -> bool:
        """Return True if Phoenix MCP tools should be registered."""
        return self.ENABLED and self.CONTENT_MODE != MCPContentMode.DISABLED

    @property
    def include_summaries(self) -> bool:
        """Return True if trace summaries should include generated text."""
        return self.CONTENT_MODE in (
            MCPContentMode.SUMMARY,
            MCPContentMode.FULL_DEV,
        )

    @property
    def include_content_snippets(self) -> bool:
        """Return True if bounded prompt/response snippets are allowed."""
        return (
            self.CONTENT_MODE == MCPContentMode.FULL_DEV
            and self.ALLOW_FULL_DEV_CONTENT
        )

    @property
    def traces_api_url(self) -> str:
        """Return the Phoenix REST API base URL for trace queries."""
        return self.ENDPOINT.rstrip("/")


# Module-level singleton
mcp_settings = PhoenixMCPSettings()
