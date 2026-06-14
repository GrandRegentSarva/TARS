"""
Tests for Phase 6 Configuration
================================
Validates Phoenix and tracing environment settings.

Tests cover:
- Default disabled state
- Content mode parsing and fallback
- Endpoint, project name, timeout, and batching settings
- Property helpers (is_tracing_enabled, capture_content, otlp_endpoint)
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from tars.phase6.config import ContentMode, PhoenixSettings


class TestContentMode:
    """Test ContentMode enum values."""

    def test_full_mode(self):
        assert ContentMode.FULL == "full"

    def test_metadata_mode(self):
        assert ContentMode.METADATA == "metadata"

    def test_disabled_mode(self):
        assert ContentMode.DISABLED == "disabled"

    def test_invalid_mode_raises(self):
        with pytest.raises(ValueError):
            ContentMode("invalid")


class TestPhoenixSettingsDefaults:
    """Test default configuration values."""

    @patch.dict(os.environ, {}, clear=True)
    def test_tracing_disabled_by_default(self):
        settings = PhoenixSettings()
        assert settings.ENABLED is False

    @patch.dict(os.environ, {}, clear=True)
    def test_default_endpoint(self):
        settings = PhoenixSettings()
        assert settings.ENDPOINT == "http://localhost:6006"

    @patch.dict(os.environ, {}, clear=True)
    def test_default_project_name(self):
        settings = PhoenixSettings()
        assert settings.PROJECT_NAME == "tars-phase5-reasoning"

    @patch.dict(os.environ, {}, clear=True)
    def test_default_content_mode_is_full(self):
        settings = PhoenixSettings()
        assert settings.CONTENT_MODE == ContentMode.FULL

    @patch.dict(os.environ, {}, clear=True)
    def test_default_export_timeout(self):
        settings = PhoenixSettings()
        assert settings.EXPORT_TIMEOUT_SECONDS == 5.0

    @patch.dict(os.environ, {}, clear=True)
    def test_default_batch_export(self):
        settings = PhoenixSettings()
        assert settings.BATCH_EXPORT is True


class TestPhoenixSettingsEnvironment:
    """Test configuration from environment variables."""

    @patch.dict(os.environ, {"PHOENIX_ENABLED": "true"})
    def test_enabled_true(self):
        settings = PhoenixSettings()
        assert settings.ENABLED is True

    @patch.dict(os.environ, {"PHOENIX_ENABLED": "1"})
    def test_enabled_one(self):
        settings = PhoenixSettings()
        assert settings.ENABLED is True

    @patch.dict(os.environ, {"PHOENIX_ENABLED": "yes"})
    def test_enabled_yes(self):
        settings = PhoenixSettings()
        assert settings.ENABLED is True

    @patch.dict(os.environ, {"PHOENIX_ENABLED": "false"})
    def test_enabled_false(self):
        settings = PhoenixSettings()
        assert settings.ENABLED is False

    @patch.dict(os.environ, {"PHOENIX_ENDPOINT": "http://phoenix:4317"})
    def test_custom_endpoint(self):
        settings = PhoenixSettings()
        assert settings.ENDPOINT == "http://phoenix:4317"

    @patch.dict(os.environ, {"PHOENIX_PROJECT_NAME": "my-project"})
    def test_custom_project_name(self):
        settings = PhoenixSettings()
        assert settings.PROJECT_NAME == "my-project"

    @patch.dict(os.environ, {"PHOENIX_CONTENT_MODE": "metadata"})
    def test_metadata_content_mode(self):
        settings = PhoenixSettings()
        assert settings.CONTENT_MODE == ContentMode.METADATA

    @patch.dict(os.environ, {"PHOENIX_CONTENT_MODE": "disabled"})
    def test_disabled_content_mode(self):
        settings = PhoenixSettings()
        assert settings.CONTENT_MODE == ContentMode.DISABLED

    @patch.dict(os.environ, {"PHOENIX_CONTENT_MODE": "invalid_mode"})
    def test_invalid_content_mode_falls_back_to_full(self):
        settings = PhoenixSettings()
        assert settings.CONTENT_MODE == ContentMode.FULL

    @patch.dict(os.environ, {"PHOENIX_EXPORT_TIMEOUT_SECONDS": "10.0"})
    def test_custom_export_timeout(self):
        settings = PhoenixSettings()
        assert settings.EXPORT_TIMEOUT_SECONDS == 10.0

    @patch.dict(os.environ, {"PHOENIX_EXPORT_TIMEOUT_SECONDS": "not_a_number"})
    def test_invalid_export_timeout_falls_back(self):
        settings = PhoenixSettings()
        assert settings.EXPORT_TIMEOUT_SECONDS == 5.0

    @patch.dict(os.environ, {"PHOENIX_BATCH_EXPORT": "false"})
    def test_batch_export_false(self):
        settings = PhoenixSettings()
        assert settings.BATCH_EXPORT is False


class TestPhoenixSettingsProperties:
    """Test computed property helpers."""

    def test_is_tracing_enabled_when_enabled_and_full(
        self, tracing_settings_enabled
    ):
        assert tracing_settings_enabled.is_tracing_enabled is True

    def test_is_tracing_enabled_when_enabled_and_metadata(
        self, tracing_settings_metadata
    ):
        assert tracing_settings_metadata.is_tracing_enabled is True

    def test_is_tracing_disabled_when_disabled(
        self, tracing_settings_disabled
    ):
        assert tracing_settings_disabled.is_tracing_enabled is False

    def test_is_tracing_disabled_when_content_mode_disabled(self):
        settings = PhoenixSettings.__new__(PhoenixSettings)
        settings.ENABLED = True
        settings.CONTENT_MODE = ContentMode.DISABLED
        assert settings.is_tracing_enabled is False

    def test_capture_content_full_mode(self, tracing_settings_enabled):
        assert tracing_settings_enabled.capture_content is True

    def test_capture_content_metadata_mode(self, tracing_settings_metadata):
        assert tracing_settings_metadata.capture_content is False

    def test_otlp_endpoint_appends_v1_traces(self, tracing_settings_enabled):
        assert tracing_settings_enabled.otlp_endpoint == (
            "http://localhost:6006/v1/traces"
        )

    def test_otlp_endpoint_no_double_suffix(self):
        settings = PhoenixSettings.__new__(PhoenixSettings)
        settings.ENDPOINT = "http://localhost:6006/v1/traces"
        assert settings.otlp_endpoint == "http://localhost:6006/v1/traces"

    def test_otlp_endpoint_strips_trailing_slash(self):
        settings = PhoenixSettings.__new__(PhoenixSettings)
        settings.ENDPOINT = "http://localhost:6006/"
        assert settings.otlp_endpoint == "http://localhost:6006/v1/traces"
