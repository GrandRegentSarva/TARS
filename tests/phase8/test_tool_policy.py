"""
Phase 8 Tool Policy Tests
===========================
Tests for introspection policy decisions.

All tests run without live Phoenix, Gemini, or MCP network services.
"""

from __future__ import annotations

import pytest

from tars.phase8.config import MCPContentMode
from tars.phase8.tool_policy import IntrospectionPolicy

from .conftest import make_settings


class TestIntrospectionPolicy:
    """Test introspection policy decisions."""

    def test_not_requested_returns_false(self):
        """Introspection not requested returns False."""
        settings = make_settings(enabled=True)
        policy = IntrospectionPolicy(settings=settings)
        assert policy.should_introspect(use_introspection=False) is False

    def test_requested_and_enabled_returns_true(self):
        """Introspection requested and enabled returns True."""
        settings = make_settings(enabled=True)
        policy = IntrospectionPolicy(settings=settings)
        assert policy.should_introspect(use_introspection=True) is True

    def test_requested_but_disabled_returns_false(self):
        """Introspection requested but MCP disabled returns False."""
        settings = make_settings(enabled=False)
        policy = IntrospectionPolicy(settings=settings)
        assert policy.should_introspect(use_introspection=True) is False

    def test_requested_but_content_disabled_returns_false(self):
        """Introspection requested but content mode disabled returns False."""
        settings = make_settings(
            enabled=True,
            content_mode=MCPContentMode.DISABLED,
        )
        policy = IntrospectionPolicy(settings=settings)
        assert policy.should_introspect(use_introspection=True) is False

    def test_should_register_tools_when_enabled(self):
        """Tools should be registered when MCP is enabled."""
        settings = make_settings(enabled=True)
        policy = IntrospectionPolicy(settings=settings)
        assert policy.should_register_tools() is True

    def test_should_not_register_tools_when_disabled(self):
        """Tools should not be registered when MCP is disabled."""
        settings = make_settings(enabled=False)
        policy = IntrospectionPolicy(settings=settings)
        assert policy.should_register_tools() is False

    def test_max_traces_from_settings(self):
        """max_traces comes from settings DEFAULT_LIMIT."""
        settings = make_settings(default_limit=7)
        policy = IntrospectionPolicy(settings=settings)
        assert policy.max_traces == 7

    def test_max_compare_ids_from_settings(self):
        """max_compare_ids comes from settings MAX_TRACE_IDS."""
        settings = make_settings(max_trace_ids=8)
        policy = IntrospectionPolicy(settings=settings)
        assert policy.max_compare_ids == 8

    def test_default_use_introspection_is_false(self):
        """Default use_introspection is False."""
        settings = make_settings(enabled=True)
        policy = IntrospectionPolicy(settings=settings)
        # Default keyword argument
        assert policy.should_introspect() is False
