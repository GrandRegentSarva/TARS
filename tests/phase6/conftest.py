"""
Phase 6 Test Fixtures
=====================
Shared fixtures for Phase 6 Phoenix integration tests.

All tests use an in-memory span exporter. No running Phoenix instance
or live Gemini credentials are required.
"""

from __future__ import annotations

import os
from typing import Any, Optional

import pytest
import pytest_asyncio

from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from tars.phase6.config import ContentMode, PhoenixSettings
from tars.phase6.tracing import reset_tracing


# =============================================================================
# Environment Helpers
# =============================================================================

@pytest.fixture(autouse=True)
def _reset_tracing_state():
    """Reset tracing state before and after each test."""
    reset_tracing()
    yield
    reset_tracing()


# =============================================================================
# In-Memory Exporter Fixtures
# =============================================================================

@pytest.fixture
def in_memory_exporter() -> InMemorySpanExporter:
    """Create a fresh in-memory span exporter."""
    return InMemorySpanExporter()


@pytest.fixture
def tracing_settings_enabled() -> PhoenixSettings:
    """Create PhoenixSettings with tracing enabled (full content mode)."""
    settings = PhoenixSettings.__new__(PhoenixSettings)
    settings.ENABLED = True
    settings.ENDPOINT = "http://localhost:6006"
    settings.PROJECT_NAME = "tars-test"
    settings.CONTENT_MODE = ContentMode.FULL
    settings.EXPORT_TIMEOUT_SECONDS = 5.0
    settings.BATCH_EXPORT = False  # Use simple processor for tests
    return settings


@pytest.fixture
def tracing_settings_metadata() -> PhoenixSettings:
    """Create PhoenixSettings with metadata-only content mode."""
    settings = PhoenixSettings.__new__(PhoenixSettings)
    settings.ENABLED = True
    settings.ENDPOINT = "http://localhost:6006"
    settings.PROJECT_NAME = "tars-test"
    settings.CONTENT_MODE = ContentMode.METADATA
    settings.EXPORT_TIMEOUT_SECONDS = 5.0
    settings.BATCH_EXPORT = False
    return settings


@pytest.fixture
def tracing_settings_disabled() -> PhoenixSettings:
    """Create PhoenixSettings with tracing disabled."""
    settings = PhoenixSettings.__new__(PhoenixSettings)
    settings.ENABLED = False
    settings.ENDPOINT = "http://localhost:6006"
    settings.PROJECT_NAME = "tars-test"
    settings.CONTENT_MODE = ContentMode.DISABLED
    settings.EXPORT_TIMEOUT_SECONDS = 5.0
    settings.BATCH_EXPORT = False
    return settings


# =============================================================================
# Incident Builder Helpers (duplicated from phase5 to avoid cross-test deps)
# =============================================================================

def make_incident(
    *,
    incident_id: str = "inc_test123",
    mission_id: str = "test_mission",
    incident_type: str = "navigation_instability",
    severity: str = "high",
    start_sequence: int = 5,
    end_sequence: int = 10,
    start_ms: int = 5000,
    end_ms: int = 10000,
    contributing_states: int = 6,
    peak_risk: float = 0.78,
    phases: Optional[list[str]] = None,
    evidence: Optional[list[str]] = None,
) -> dict[str, Any]:
    """Build an incident dict matching Phase 4 Incident structure."""
    return {
        "incident_id": incident_id,
        "mission_id": mission_id,
        "incident_type": incident_type,
        "severity": severity,
        "start_sequence": start_sequence,
        "end_sequence": end_sequence,
        "start_ms": start_ms,
        "end_ms": end_ms,
        "contributing_states": contributing_states,
        "peak_risk": peak_risk,
        "phases": phases or ["cruise"],
        "evidence": evidence or [
            "GPS quality degraded during flight",
            "attitude unstable while cruising",
        ],
    }


def make_battery_incident(
    incident_id: str = "inc_battery_001",
) -> dict[str, Any]:
    """Build a battery degradation incident."""
    return make_incident(
        incident_id=incident_id,
        incident_type="battery_degradation",
        severity="medium",
        peak_risk=0.55,
        evidence=[
            "Battery level dropping faster than expected",
            "Battery voltage below nominal threshold",
        ],
    )
