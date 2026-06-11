"""
Phase 4 Test Fixtures
=====================
Shared fixtures and builders for Phase 4 incident engine tests.

State builder functions create dicts matching the Phase 3 StateSnapshot
structure so tests don't depend on Phase 3 Pydantic imports.

Redis tests use DB 15 and skip if Redis is unavailable.
"""

from __future__ import annotations

import socket
from datetime import datetime, timezone
from typing import Any, Optional

import pytest
import pytest_asyncio

from tars.phase4.store import IncidentStore


# =============================================================================
# State Builder Helpers
# =============================================================================

def make_state(
    *,
    sequence: int = 1,
    elapsed_ms: int = 1000,
    phase: str = "cruise",
    health: str = "nominal",
    risk: float = 0.1,
    gps_quality: str = "normal",
    battery_level: str = "normal",
    altitude_stability: str = "normal",
    attitude_stability: str = "normal",
    relative_altitude_m: Optional[float] = 20.0,
    ground_speed_m_s: Optional[float] = 5.0,
    battery_percent: Optional[float] = 85.0,
    gps_satellites: Optional[int] = 12,
    roll_abs_deg: Optional[float] = 2.0,
    pitch_abs_deg: Optional[float] = 1.5,
    reasons: Optional[list[str]] = None,
) -> dict[str, Any]:
    """
    Build a state dict matching Phase 3 StateSnapshot structure.

    All parameters have nominal defaults so tests only need to override
    the fields relevant to the scenario being tested.
    """
    return {
        "mission_id": "test_mission",
        "sequence": sequence,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "elapsed_ms": elapsed_ms,
        "phase": phase,
        "health": health,
        "risk": risk,
        "signals": {
            "gps_quality": gps_quality,
            "battery_level": battery_level,
            "altitude_stability": altitude_stability,
            "attitude_stability": attitude_stability,
        },
        "metrics": {
            "relative_altitude_m": relative_altitude_m,
            "ground_speed_m_s": ground_speed_m_s,
            "battery_percent": battery_percent,
            "gps_satellites": gps_satellites,
            "roll_abs_deg": roll_abs_deg,
            "pitch_abs_deg": pitch_abs_deg,
        },
        "reasons": reasons or [],
    }


def make_states(
    count: int,
    start_sequence: int = 1,
    interval_ms: int = 1000,
    **overrides: Any,
) -> list[dict[str, Any]]:
    """
    Build a list of state dicts with sequential timing.

    Args:
        count: Number of states to generate.
        start_sequence: Starting sequence number.
        interval_ms: Milliseconds between states.
        **overrides: Fields to override in every state.

    Returns:
        List of state dicts.
    """
    states = []
    for i in range(count):
        state = make_state(
            sequence=start_sequence + i,
            elapsed_ms=(start_sequence + i) * interval_ms,
            **overrides,
        )
        states.append(state)
    return states


def make_nominal_states(count: int = 10) -> list[dict[str, Any]]:
    """Build a list of completely nominal states (no incidents expected)."""
    return make_states(count, phase="cruise", health="nominal", risk=0.1)


def make_gps_degraded_states(
    count: int = 5,
    gps_quality: str = "weak",
    risk: float = 0.4,
) -> list[dict[str, Any]]:
    """Build states with GPS degradation during cruise."""
    return make_states(
        count,
        phase="cruise",
        health="degraded",
        risk=risk,
        gps_quality=gps_quality,
    )


def make_critical_health_state(sequence: int = 1) -> dict[str, Any]:
    """Build a single state with critical health."""
    return make_state(
        sequence=sequence,
        elapsed_ms=sequence * 1000,
        phase="cruise",
        health="critical",
        risk=0.85,
        gps_quality="missing",
        reasons=["Global position not ok", "GPS signal missing"],
    )


def make_high_risk_states(
    count: int = 5,
    risk: float = 0.85,
) -> list[dict[str, Any]]:
    """Build states with high risk scores."""
    return make_states(
        count,
        phase="cruise",
        health="degraded",
        risk=risk,
        gps_quality="weak",
        attitude_stability="weak",
    )


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
async def incident_store():
    """Create an IncidentStore connected to test DB 15, cleaned after use."""
    store = IncidentStore(redis_url=_TEST_REDIS_URL)
    await store.connect()

    yield store

    # Cleanup: flush test DB
    await store.redis.flushdb()
    await store.close()
