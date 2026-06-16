"""
Phase 8 Configuration Tests
============================
Tests for Phoenix MCP settings, limits, timeout, and content mode.

All tests run without live Phoenix, Gemini, or MCP network services.
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from tars.phase8.config import MCPContentMode, PhoenixMCPSettings


class TestPhoenixMCPSettings:
    """Test Phoenix MCP configuration loading."""

    def test_disabled_by_default(self):
        """MCP is disabled by default."""
        with patch.dict(os.environ, {}, clear=True):
            settings = PhoenixMCPSettings()
        assert settings.ENABLED is False
        assert settings.is_enabled is False

    def test_enabled_when_set(self):
        """MCP is enabled when PHOENIX_MCP_ENABLED=true."""
        with patch.dict(os.environ, {"PHOENIX_MCP_ENABLED": "true"}, clear=True):
            settings = PhoenixMCPSettings()
        assert settings.ENABLED is True

    def test_default_content_mode_is_metadata(self):
        """Default content mode is metadata."""
        with patch.dict(os.environ, {}, clear=True):
            settings = PhoenixMCPSettings()
        assert settings.CONTENT_MODE == MCPContentMode.METADATA

    def test_summary_content_mode(self):
        """Summary content mode loads correctly."""
        with patch.dict(os.environ, {"PHOENIX_MCP_CONTENT_MODE": "summary"}, clear=True):
            settings = PhoenixMCPSettings()
        assert settings.CONTENT_MODE == MCPContentMode.SUMMARY

    def test_full_dev_content_mode_requires_opt_in(self):
        """full_dev mode falls back to summary without explicit opt-in."""
        with patch.dict(os.environ, {
            "PHOENIX_MCP_CONTENT_MODE": "full_dev",
            "PHOENIX_MCP_ALLOW_FULL_DEV_CONTENT": "false",
        }, clear=True):
            settings = PhoenixMCPSettings()
        assert settings.CONTENT_MODE == MCPContentMode.SUMMARY

    def test_full_dev_content_mode_with_opt_in(self):
        """full_dev mode works with explicit opt-in."""
        with patch.dict(os.environ, {
            "PHOENIX_MCP_CONTENT_MODE": "full_dev",
            "PHOENIX_MCP_ALLOW_FULL_DEV_CONTENT": "true",
        }, clear=True):
            settings = PhoenixMCPSettings()
        assert settings.CONTENT_MODE == MCPContentMode.FULL_DEV

    def test_invalid_content_mode_disables_tools(self):
        """Invalid content mode disables tool registration."""
        with patch.dict(os.environ, {
            "PHOENIX_MCP_CONTENT_MODE": "invalid_mode",
        }, clear=True):
            settings = PhoenixMCPSettings()
        assert settings.CONTENT_MODE == MCPContentMode.DISABLED
        assert settings.is_enabled is False

    def test_disabled_content_mode(self):
        """Disabled content mode prevents tool registration."""
        with patch.dict(os.environ, {
            "PHOENIX_MCP_ENABLED": "true",
            "PHOENIX_MCP_CONTENT_MODE": "disabled",
        }, clear=True):
            settings = PhoenixMCPSettings()
        assert settings.is_enabled is False

    def test_timeout_is_bounded(self):
        """Timeout must be positive."""
        with patch.dict(os.environ, {
            "PHOENIX_MCP_TIMEOUT_SECONDS": "-1",
        }, clear=True):
            settings = PhoenixMCPSettings()
        assert settings.TIMEOUT_SECONDS == 5.0

    def test_timeout_parses_correctly(self):
        """Valid timeout parses correctly."""
        with patch.dict(os.environ, {
            "PHOENIX_MCP_TIMEOUT_SECONDS": "3.0",
        }, clear=True):
            settings = PhoenixMCPSettings()
        assert settings.TIMEOUT_SECONDS == 3.0

    def test_invalid_timeout_uses_default(self):
        """Invalid timeout uses default."""
        with patch.dict(os.environ, {
            "PHOENIX_MCP_TIMEOUT_SECONDS": "not_a_number",
        }, clear=True):
            settings = PhoenixMCPSettings()
        assert settings.TIMEOUT_SECONDS == 5.0

    def test_limits_are_bounded(self):
        """Limits are bounded to positive values."""
        with patch.dict(os.environ, {
            "PHOENIX_MCP_DEFAULT_LIMIT": "0",
            "PHOENIX_MCP_MAX_LIMIT": "0",
        }, clear=True):
            settings = PhoenixMCPSettings()
        assert settings.DEFAULT_LIMIT >= 1
        assert settings.MAX_LIMIT >= 1

    def test_default_limit_capped_to_max(self):
        """Default limit is capped to max limit."""
        with patch.dict(os.environ, {
            "PHOENIX_MCP_DEFAULT_LIMIT": "50",
            "PHOENIX_MCP_MAX_LIMIT": "10",
        }, clear=True):
            settings = PhoenixMCPSettings()
        assert settings.DEFAULT_LIMIT <= settings.MAX_LIMIT

    def test_max_summary_chars_minimum(self):
        """Max summary chars has a minimum of 100."""
        with patch.dict(os.environ, {
            "PHOENIX_MCP_MAX_SUMMARY_CHARS": "10",
        }, clear=True):
            settings = PhoenixMCPSettings()
        assert settings.MAX_SUMMARY_CHARS >= 100

    def test_include_summaries_property(self):
        """include_summaries is True for summary and full_dev modes."""
        with patch.dict(os.environ, {
            "PHOENIX_MCP_CONTENT_MODE": "summary",
        }, clear=True):
            settings = PhoenixMCPSettings()
        assert settings.include_summaries is True

    def test_include_content_snippets_property(self):
        """include_content_snippets requires full_dev with opt-in."""
        with patch.dict(os.environ, {
            "PHOENIX_MCP_CONTENT_MODE": "full_dev",
            "PHOENIX_MCP_ALLOW_FULL_DEV_CONTENT": "true",
        }, clear=True):
            settings = PhoenixMCPSettings()
        assert settings.include_content_snippets is True

    def test_metadata_mode_no_content_snippets(self):
        """Metadata mode does not include content snippets."""
        with patch.dict(os.environ, {
            "PHOENIX_MCP_CONTENT_MODE": "metadata",
        }, clear=True):
            settings = PhoenixMCPSettings()
        assert settings.include_content_snippets is False

    def test_traces_api_url(self):
        """traces_api_url strips trailing slash."""
        with patch.dict(os.environ, {
            "PHOENIX_MCP_ENDPOINT": "http://phoenix:6006/",
        }, clear=True):
            settings = PhoenixMCPSettings()
        assert settings.traces_api_url == "http://phoenix:6006"
