"""
Phase 5 Test Fixtures
=====================
Shared fixtures and builders for Phase 5 reasoning layer tests.

Incident builder functions create dicts matching the Phase 4 Incident
structure so tests don't depend on Phase 4 Pydantic imports.

Redis tests use DB 15 and skip if Redis is unavailable.
"""

from __future__ import annotations

import socket
from typing import Any, Optional

import pytest
import pytest_asyncio

from tars.phase5.models import ReasoningAnalysis
from tars.phase5.provider import FakeReasoningProvider
from tars.phase5.store import ReasoningStore


# =============================================================================
# Incident Builder Helpers
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
    """
    Build an incident dict matching Phase 4 Incident structure.

    All parameters have defaults so tests only need to override
    the fields relevant to the scenario being tested.
    """
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


def make_critical_incident(
    incident_id: str = "inc_critical_001",
) -> dict[str, Any]:
    """Build a critical severity incident."""
    return make_incident(
        incident_id=incident_id,
        incident_type="sensor_health_failure",
        severity="critical",
        peak_risk=0.92,
        contributing_states=12,
        evidence=[
            "Multiple sensor health checks failed",
            "GPS signal completely lost",
            "Magnetometer calibration invalid",
        ],
    )


def make_minimal_incident(
    incident_id: str = "inc_minimal_001",
) -> dict[str, Any]:
    """Build an incident with minimal evidence."""
    return make_incident(
        incident_id=incident_id,
        incident_type="telemetry_degradation",
        severity="low",
        peak_risk=0.25,
        contributing_states=3,
        evidence=["Telemetry update rate decreased"],
    )


# =============================================================================
# Provider Fixtures
# =============================================================================

@pytest.fixture
def fake_provider() -> FakeReasoningProvider:
    """Create a configured fake reasoning provider."""
    return FakeReasoningProvider()


@pytest.fixture
def unconfigured_provider() -> FakeReasoningProvider:
    """Create an unconfigured fake reasoning provider."""
    return FakeReasoningProvider(configured=False)


@pytest.fixture
def failing_provider() -> FakeReasoningProvider:
    """Create a fake provider that always fails."""
    return FakeReasoningProvider(fail=True, fail_message="Test failure")


# =============================================================================
# Redis Fixtures
# =============================================================================

def _redis_is_reachable(host: str = "localhost", port: int = 6379) -> bool:
    """Check if Redis is reachable via TCP."""
    try:
        with socket.create_connection((host, port), timeout=2.0):
            return True
    except OSError:
        return False


# Use DB 15 for tests to avoid interfering with development data
_TEST_REDIS_URL = "redis://localhost:6379/15"

# Skip Redis tests if Redis is not available
requires_redis = pytest.mark.skipif(
    not _redis_is_reachable(),
    reason="Redis not available on localhost:6379",
)


@pytest_asyncio.fixture
async def reasoning_store():
    """Create a ReasoningStore connected to test DB 15, cleaned after use."""
    store = ReasoningStore(redis_url=_TEST_REDIS_URL)
    await store.connect()

    yield store

    # Cleanup: flush test DB
    await store.redis.flushdb()
    await store.close()
