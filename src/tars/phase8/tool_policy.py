"""
Tool Policy
============
Rules for when Phase 5 may call the Phoenix MCP introspection tools.

Policy decisions:
- Introspection is only allowed when explicitly requested via
  ``use_introspection=True`` on the analyze request.
- Phoenix MCP must be enabled in configuration.
- The content mode must not be ``disabled``.
- Tool calls are bounded by configured limits.
- Tool failures never prevent Phase 5 reasoning from completing.

The policy does not decide *what* to search for -- that is the
service's responsibility. The policy only decides *whether* to search.
"""

from __future__ import annotations

import logging
from typing import Optional

from .config import MCPContentMode, PhoenixMCPSettings, mcp_settings

logger = logging.getLogger("phase8.tool_policy")


class IntrospectionPolicy:
    """
    Determines whether Phase 5 reasoning may use introspection tools.

    All decisions are logged for observability.
    """

    def __init__(
        self,
        settings: Optional[PhoenixMCPSettings] = None,
    ) -> None:
        self._settings = settings or mcp_settings

    def should_introspect(
        self,
        *,
        use_introspection: bool = False,
    ) -> bool:
        """
        Determine whether introspection should be performed.

        Args:
            use_introspection: Whether the request explicitly asked
                for introspection.

        Returns:
            True if introspection should proceed.
        """
        # Must be explicitly requested
        if not use_introspection:
            logger.debug("Introspection not requested")
            return False

        # MCP must be enabled
        if not self._settings.is_enabled:
            logger.debug(
                "Introspection requested but Phoenix MCP is disabled"
            )
            return False

        # Content mode must not be disabled
        if self._settings.CONTENT_MODE == MCPContentMode.DISABLED:
            logger.debug(
                "Introspection requested but content mode is disabled"
            )
            return False

        logger.info("Introspection approved for this reasoning request")
        return True

    def should_register_tools(self) -> bool:
        """
        Determine whether MCP tools should be registered at startup.

        Returns:
            True if tools should be registered.
        """
        return self._settings.is_enabled

    @property
    def max_traces(self) -> int:
        """Maximum number of traces to fetch for introspection."""
        return self._settings.DEFAULT_LIMIT

    @property
    def max_compare_ids(self) -> int:
        """Maximum number of trace IDs for comparison."""
        return self._settings.MAX_TRACE_IDS
