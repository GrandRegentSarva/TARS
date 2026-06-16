"""
MCP Tool Adapter
================
Exposes Phoenix trace search as analysis-only, read-only tools
compatible with MCP (Model Context Protocol) tool calling.

Tool contract:
- ``search_reasoning_traces``: Search Phoenix for traces matching
  operational identifiers or classifications.
- ``get_reasoning_trace_summary``: Return a safe summary for one trace.
- ``compare_reasoning_traces``: Compare a small set of traces and
  summarize repeated patterns.

Safety guarantees:
- All tools are read-only. No mutations to Phoenix, Redis, PostgreSQL,
  Neo4j, PX4, MAVSDK, or upstream APIs.
- No arbitrary query strings or unrestricted trace export.
- Trace ID and result limits are enforced.
- Empty results returned when MCP is disabled.
- Comparison output is descriptive, not evaluative.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from .config import PhoenixMCPSettings, mcp_settings
from .models import (
    TraceCompareRequest,
    TraceCompareResponse,
    TraceSearchRequest,
    TraceSearchResponse,
    TraceSummaryRequest,
    TraceSummaryResponse,
)

logger = logging.getLogger("phase8.mcp_tools")


# =============================================================================
# Tool Definitions (MCP-compatible schemas)
# =============================================================================

TOOL_SEARCH_REASONING_TRACES = {
    "name": "search_reasoning_traces",
    "description": (
        "Search Phoenix for prior reasoning traces matching operational "
        "identifiers or classifications. Returns bounded trace metadata. "
        "This is an analysis-only tool that does not modify any data."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "mission_id": {
                "type": "string",
                "description": "Filter by mission identifier.",
            },
            "incident_id": {
                "type": "string",
                "description": "Filter by incident identifier.",
            },
            "incident_type": {
                "type": "string",
                "description": "Filter by incident type classification.",
            },
            "root_cause": {
                "type": "string",
                "description": "Filter by root cause classification.",
            },
            "prompt_version": {
                "type": "string",
                "description": "Filter by prompt version.",
            },
            "model": {
                "type": "string",
                "description": "Filter by model identifier.",
            },
            "outcome": {
                "type": "string",
                "enum": ["success", "failed", "cached"],
                "description": "Filter by outcome.",
            },
            "from_time": {
                "type": "string",
                "description": "Start of time range (ISO 8601).",
            },
            "to_time": {
                "type": "string",
                "description": "End of time range (ISO 8601).",
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of traces to return.",
                "default": 5,
                "minimum": 1,
                "maximum": 20,
            },
        },
        "required": [],
    },
}

TOOL_GET_REASONING_TRACE_SUMMARY = {
    "name": "get_reasoning_trace_summary",
    "description": (
        "Return a safe summary for one reasoning trace including "
        "stage breakdown, timing, and status. "
        "This is an analysis-only tool that does not modify any data."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "trace_id": {
                "type": "string",
                "description": "Phoenix trace identifier.",
            },
        },
        "required": ["trace_id"],
    },
}

TOOL_COMPARE_REASONING_TRACES = {
    "name": "compare_reasoning_traces",
    "description": (
        "Compare a small set of reasoning traces and summarize "
        "repeated patterns. The comparison is descriptive only and "
        "does not produce evaluation scores or accuracy labels. "
        "This is an analysis-only tool that does not modify any data."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "trace_ids": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of trace IDs to compare (max 10).",
                "minItems": 1,
                "maxItems": 10,
            },
        },
        "required": ["trace_ids"],
    },
}

# All registered tools
ALL_TOOLS = [
    TOOL_SEARCH_REASONING_TRACES,
    TOOL_GET_REASONING_TRACE_SUMMARY,
    TOOL_COMPARE_REASONING_TRACES,
]


def get_tool_definitions(
    settings: Optional[PhoenixMCPSettings] = None,
) -> list[dict[str, Any]]:
    """
    Return the list of MCP tool definitions.

    Returns an empty list when MCP is disabled.

    Args:
        settings: Optional settings override.

    Returns:
        List of tool definition dicts.
    """
    cfg = settings or mcp_settings
    if not cfg.is_enabled:
        return []
    return list(ALL_TOOLS)


def get_tool_names(
    settings: Optional[PhoenixMCPSettings] = None,
) -> list[str]:
    """
    Return the names of registered MCP tools.

    Returns an empty list when MCP is disabled.
    """
    return [t["name"] for t in get_tool_definitions(settings)]
