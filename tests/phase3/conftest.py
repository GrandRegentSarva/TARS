"""
Phase 3 Test Fixtures
=====================
Shared fixtures for Phase 3 State Engine tests.

Pure state logic tests (phase_classifier, risk, state_processor) require
no external services and always run.

Redis-backed tests (store, api) use a SEPARATE Redis database (DB 15)
to avoid destroying development data. They skip if Redis is not reachable.
"""

from __future__ import annotations

import socket
from datetime import datetime, timezone, timedelta
from typing import Any
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio

from tars.phase3.models import (
    ReplayData,
    StateSnapshot,
    TelemetryFrame,
    MissionPhase,
    HealthStatus,
)
from tars.phase3.store import StateStore


# ---------------------------------------------------------------------------
# Redis connectivity check
# ---------------------------------------------------------------------------
TEST_REDIS_URL = "redis://localhost:6379/15"


def _redis_is_reachable(host: str = "localhost", port: int = 6379, timeout: float = 2.0) -> bool:
    """Synchronous TCP check for Redis."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (OSError, ConnectionRefusedError, TimeoutError):
        return False


_REDIS_AVAILABLE = _redis_is_reachable()


# ---------------------------------------------------------------------------
# Sample telemetry builders
# ---------------------------------------------------------------------------

def make_telemetry(
    altitude: float = 20.0,
    flight_mode: str = "MISSION",
    battery_percent: float = 85.0,
    gps_satellites: int = 12,
    gps_fix: str = "FIX_3D",
    roll_deg: float = 1.0,
    pitch_deg: float = -0.5,
    north_m_s: float = 2.0,
    east_m_s: float = 1.0,
    down_m_s: float = -0.1,
    health_flags: dict[str, bool] | None = None,
) -> dict[str, Any]:
    """Build a valid telemetry dict matching Phase 1 TelemetrySnapshot structure."""
    if health_flags is None:
        health_flags = {
            "is_gyrometer_calibration_ok": True,
            "is_accelerometer_calibration_ok": True,
            "is_magnetometer_calibration_ok": True,
            "is_home_position_ok": True,
            "is_global_position_ok": True,
        }

    return {
        "position": {
            "latitude_deg": 47.3977,
            "longitude_deg": 8.5456,
            "absolute_altitude_m": 488.0 + altitude,
            "relative_altitude_m": altitude,
        },
        "velocity": {
            "north_m_s": north_m_s,
            "east_m_s": east_m_s,
            "down_m_s": down_m_s,
        },
        "battery": {
            "voltage_v": 12.0,
            "remaining_percent": battery_percent,
        },
        "gps": {
            "num_satellites": gps_satellites,
            "fix_type": gps_fix,
        },
        "attitude": {
            "roll_deg": roll_deg,
            "pitch_deg": pitch_deg,
            "yaw_deg": 90.0,
        },
        "flight_mode": flight_mode,
        "health": health_flags,
    }


def make_frame(
    sequence: int = 0,
    elapsed_ms: int = 0,
    **telemetry_kwargs: Any,
) -> TelemetryFrame:
    """Build a TelemetryFrame with configurable telemetry."""
    return TelemetryFrame(
        sequence=sequence,
        elapsed_ms=elapsed_ms,
        timestamp=datetime(2026, 6, 8, 6, 30, 0, tzinfo=timezone.utc)
        + timedelta(milliseconds=elapsed_ms),
        telemetry=make_telemetry(**telemetry_kwargs),
    )


def make_replay_frames(
    mission_id: str = "test_mission_001",
    num_frames: int = 5,
    start_altitude: float = 0.0,
    altitude_step: float = 5.0,
    flight_mode: str = "MISSION",
) -> list[TelemetryFrame]:
    """Build a list of TelemetryFrames simulating a mission."""
    frames: list[TelemetryFrame] = []
    for i in range(num_frames):
        altitude = start_altitude + i * altitude_step
        frames.append(
            make_frame(
                sequence=i,
                elapsed_ms=i * 1000,
                altitude=altitude,
                flight_mode=flight_mode,
                battery_percent=95.0 - i * 2.0,
            )
        )
    return frames


def make_replay_data(
    mission_id: str = "test_mission_001",
    num_frames: int = 5,
    **kwargs: Any,
) -> ReplayData:
    """Build a ReplayData response with configurable frames."""
    frames = make_replay_frames(mission_id=mission_id, num_frames=num_frames, **kwargs)
    return ReplayData(
        mission_id=mission_id,
        speed=1.0,
        from_ms=0,
        to_ms=None,
        total_frames=len(frames),
        frames=frames,
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_telemetry() -> dict[str, Any]:
    """Return a valid telemetry dict."""
    return make_telemetry()


@pytest.fixture
def sample_frame() -> TelemetryFrame:
    """Return a valid TelemetryFrame."""
    return make_frame()


@pytest.fixture
def sample_frames() -> list[TelemetryFrame]:
    """Return a list of TelemetryFrames simulating a mission."""
    return make_replay_frames()


# ---------------------------------------------------------------------------
# Redis fixtures (skip if Redis not available)
# ---------------------------------------------------------------------------

@pytest.fixture
def require_redis():
    """Skip test if Redis is not reachable."""
    if not _REDIS_AVAILABLE:
        pytest.skip("Redis not reachable at localhost:6379")


@pytest_asyncio.fixture
async def redis_store(require_redis):
    """
    Yield a StateStore connected to test Redis DB 15.

    Flushes DB 15 before and after tests.
    """
    store = StateStore(redis_url=TEST_REDIS_URL)
    await store.connect()

    # Flush test database
    await store.redis.flushdb()

    yield store

    # Cleanup
    await store.redis.flushdb()
    await store.close()
