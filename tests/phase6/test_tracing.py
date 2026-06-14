"""
Tests for Phase 6 Tracing Bootstrap
=====================================
Validates tracer provider setup, no-op behavior, exporter configuration,
idempotent initialization, and shutdown flushing.

All tests use an in-memory span exporter. No running Phoenix instance
is required.
"""

from __future__ import annotations

import pytest

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from tars.phase6.config import ContentMode, PhoenixSettings
from tars.phase6.tracing import (
    get_provider,
    get_tracer,
    init_tracing,
    is_tracing_active,
    reset_tracing,
    shutdown_tracing,
)


class TestDisabledTracing:
    """Test behavior when tracing is disabled."""

    def test_disabled_returns_noop_tracer(self, tracing_settings_disabled):
        tracer = init_tracing(settings=tracing_settings_disabled)
        assert tracer is not None
        # No-op tracer should not create real spans
        with tracer.start_as_current_span("test") as span:
            assert not span.is_recording()

    def test_disabled_tracing_not_active(self, tracing_settings_disabled):
        init_tracing(settings=tracing_settings_disabled)
        assert is_tracing_active() is False

    def test_disabled_provider_is_none(self, tracing_settings_disabled):
        init_tracing(settings=tracing_settings_disabled)
        assert get_provider() is None


class TestEnabledTracing:
    """Test behavior when tracing is enabled with in-memory exporter."""

    def test_enabled_returns_real_tracer(
        self, tracing_settings_enabled, in_memory_exporter
    ):
        tracer = init_tracing(
            settings=tracing_settings_enabled,
            exporter=in_memory_exporter,
        )
        assert tracer is not None
        with tracer.start_as_current_span("test") as span:
            assert span.is_recording()

    def test_enabled_tracing_is_active(
        self, tracing_settings_enabled, in_memory_exporter
    ):
        init_tracing(
            settings=tracing_settings_enabled,
            exporter=in_memory_exporter,
        )
        assert is_tracing_active() is True

    def test_enabled_provider_is_set(
        self, tracing_settings_enabled, in_memory_exporter
    ):
        init_tracing(
            settings=tracing_settings_enabled,
            exporter=in_memory_exporter,
        )
        provider = get_provider()
        assert provider is not None
        assert isinstance(provider, TracerProvider)

    def test_spans_exported_to_in_memory(
        self, tracing_settings_enabled, in_memory_exporter
    ):
        tracer = init_tracing(
            settings=tracing_settings_enabled,
            exporter=in_memory_exporter,
        )
        with tracer.start_as_current_span("test_span"):
            pass

        spans = in_memory_exporter.get_finished_spans()
        assert len(spans) == 1
        assert spans[0].name == "test_span"

    def test_resource_has_service_name(
        self, tracing_settings_enabled, in_memory_exporter
    ):
        init_tracing(
            settings=tracing_settings_enabled,
            exporter=in_memory_exporter,
        )
        provider = get_provider()
        resource_attrs = dict(provider.resource.attributes)
        assert resource_attrs.get("service.name") == "tars-reasoning"

    def test_resource_has_project_name(
        self, tracing_settings_enabled, in_memory_exporter
    ):
        init_tracing(
            settings=tracing_settings_enabled,
            exporter=in_memory_exporter,
        )
        provider = get_provider()
        resource_attrs = dict(provider.resource.attributes)
        assert resource_attrs.get("project.name") == "tars-test"


class TestIdempotentInitialization:
    """Test that repeated initialization is safe."""

    def test_repeated_init_returns_tracer(
        self, tracing_settings_enabled, in_memory_exporter
    ):
        tracer1 = init_tracing(
            settings=tracing_settings_enabled,
            exporter=in_memory_exporter,
        )
        tracer2 = init_tracing(
            settings=tracing_settings_enabled,
        )
        # Both should return valid tracers
        assert tracer1 is not None
        assert tracer2 is not None

    def test_repeated_init_does_not_crash(
        self, tracing_settings_enabled, in_memory_exporter
    ):
        for _ in range(5):
            init_tracing(
                settings=tracing_settings_enabled,
                exporter=in_memory_exporter,
            )
        assert is_tracing_active() is True


class TestShutdown:
    """Test tracing shutdown behavior."""

    def test_shutdown_clears_provider(
        self, tracing_settings_enabled, in_memory_exporter
    ):
        init_tracing(
            settings=tracing_settings_enabled,
            exporter=in_memory_exporter,
        )
        assert is_tracing_active() is True

        shutdown_tracing()
        assert is_tracing_active() is False
        assert get_provider() is None

    def test_shutdown_without_init_is_safe(self):
        # Should not raise
        shutdown_tracing()
        assert is_tracing_active() is False

    def test_shutdown_then_reinit(
        self, tracing_settings_enabled, in_memory_exporter
    ):
        init_tracing(
            settings=tracing_settings_enabled,
            exporter=in_memory_exporter,
        )
        shutdown_tracing()

        # Re-initialize with a new exporter
        new_exporter = InMemorySpanExporter()
        tracer = init_tracing(
            settings=tracing_settings_enabled,
            exporter=new_exporter,
        )
        assert is_tracing_active() is True

        with tracer.start_as_current_span("after_reinit"):
            pass

        spans = new_exporter.get_finished_spans()
        assert len(spans) == 1
        assert spans[0].name == "after_reinit"


class TestGetTracer:
    """Test get_tracer() fallback behavior."""

    def test_get_tracer_before_init_returns_tracer(self):
        tracer = get_tracer()
        assert tracer is not None

    def test_get_tracer_after_init_returns_tracer(
        self, tracing_settings_enabled, in_memory_exporter
    ):
        init_tracing(
            settings=tracing_settings_enabled,
            exporter=in_memory_exporter,
        )
        tracer = get_tracer()
        assert tracer is not None


class TestResetTracing:
    """Test reset_tracing() for test isolation."""

    def test_reset_clears_state(
        self, tracing_settings_enabled, in_memory_exporter
    ):
        init_tracing(
            settings=tracing_settings_enabled,
            exporter=in_memory_exporter,
        )
        assert is_tracing_active() is True

        reset_tracing()
        assert is_tracing_active() is False
        assert get_provider() is None

    def test_reset_without_init_is_safe(self):
        reset_tracing()
        assert is_tracing_active() is False
