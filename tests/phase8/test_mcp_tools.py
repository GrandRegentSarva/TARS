"""
Phase 8 MCP Tool Tests
=======================
Tests for MCP tool registration and schemas.

All tests run without live Phoenix, Gemini, or MCP network services.
"""

from __future__ import annotations

import pytest

from tars.phase8.config import MCPContentMode
from tars.phase8.mcp_tools import (
    ALL_TOOLS,
    TOOL_COMPARE_REASONING_TRACES,
    TOOL_GET_REASONING_TRACE_SUMMARY,
    TOOL_SEARCH_REASONING_TRACES,
    get_tool_definitions,
    get_tool_names,
)

from .conftest import make_settings


class TestToolRegistration:
    """Test MCP tool registration."""

    def test_registers_three_tools(self):
        """Three tools are registered when enabled."""
        settings = make_settings(enabled=True)
        tools = get_tool_definitions(settings)
        assert len(tools) == 3

    def test_tool_names(self):
        """Tool names match expected values."""
        settings = make_settings(enabled=True)
        names = get_tool_names(settings)
        assert "search_reasoning_traces" in names
        assert "get_reasoning_trace_summary" in names
        assert "compare_reasoning_traces" in names

    def test_disabled_returns_empty(self):
        """Disabled MCP returns no tools."""
        settings = make_settings(enabled=False)
        tools = get_tool_definitions(settings)
        assert tools == []

    def test_disabled_content_mode_returns_empty(self):
        """Disabled content mode returns no tools."""
        settings = make_settings(
            enabled=True,
            content_mode=MCPContentMode.DISABLED,
        )
        tools = get_tool_definitions(settings)
        assert tools == []


class TestToolSchemas:
    """Test MCP tool schema definitions."""

    def test_search_tool_has_description(self):
        """Search tool has a description."""
        assert "description" in TOOL_SEARCH_REASONING_TRACES
        assert "analysis-only" in TOOL_SEARCH_REASONING_TRACES["description"]

    def test_search_tool_no_required_params(self):
        """Search tool has no required parameters."""
        params = TOOL_SEARCH_REASONING_TRACES["parameters"]
        assert params.get("required", []) == []

    def test_search_tool_has_limit(self):
        """Search tool has a limit parameter with bounds."""
        props = TOOL_SEARCH_REASONING_TRACES["parameters"]["properties"]
        assert "limit" in props
        assert props["limit"]["minimum"] == 1
        assert props["limit"]["maximum"] == 20

    def test_search_tool_outcome_enum(self):
        """Search tool outcome has enum values."""
        props = TOOL_SEARCH_REASONING_TRACES["parameters"]["properties"]
        assert "outcome" in props
        assert set(props["outcome"]["enum"]) == {"success", "failed", "cached"}

    def test_summary_tool_requires_trace_id(self):
        """Summary tool requires trace_id."""
        params = TOOL_GET_REASONING_TRACE_SUMMARY["parameters"]
        assert "trace_id" in params["required"]

    def test_compare_tool_requires_trace_ids(self):
        """Compare tool requires trace_ids."""
        params = TOOL_COMPARE_REASONING_TRACES["parameters"]
        assert "trace_ids" in params["required"]

    def test_compare_tool_max_items(self):
        """Compare tool limits trace_ids to 10."""
        props = TOOL_COMPARE_REASONING_TRACES["parameters"]["properties"]
        assert props["trace_ids"]["maxItems"] == 10

    def test_all_tools_are_read_only(self):
        """All tools are described as analysis-only."""
        for tool in ALL_TOOLS:
            assert "analysis-only" in tool["description"].lower() or \
                   "does not modify" in tool["description"].lower()

    def test_no_mutation_tools(self):
        """No tools allow mutation operations."""
        mutation_keywords = [
            "write", "delete", "update", "create", "mutate",
            "execute", "command", "send",
        ]
        for tool in ALL_TOOLS:
            name = tool["name"].lower()
            for keyword in mutation_keywords:
                assert keyword not in name, (
                    f"Tool '{tool['name']}' name contains mutation keyword '{keyword}'"
                )

    def test_no_arbitrary_query_tool(self):
        """No tool accepts arbitrary query strings."""
        for tool in ALL_TOOLS:
            props = tool["parameters"]["properties"]
            for prop_name, prop_def in props.items():
                # No property should be named "query" or "raw_query"
                assert prop_name not in ("query", "raw_query", "graphql"), (
                    f"Tool '{tool['name']}' has arbitrary query parameter '{prop_name}'"
                )
