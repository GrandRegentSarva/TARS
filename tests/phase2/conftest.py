"""
Phase 2 Test Fixtures
=====================
Shared fixtures for Phase 2 tests.

Uses a SEPARATE test database (tars_test) to avoid destroying production data.
Tests create and drop tables per session to ensure isolation.
Skips the entire test suite fast if PostgreSQL is not reachable.
"""

from __future__ import annotations

import json
import os
import socket
import tempfile
from datetime import datetime, timezone, timedelta

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from tars.phase2.models.db import Base
from tars.phase2.database import get_session, check_database
from tars.phase2.api import app


# ---------------------------------------------------------------------------
# Database URL for tests -- uses a SEPARATE database (tars_test)
# Never defaults to the production tars database.
# ---------------------------------------------------------------------------
TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://tars:tars@localhost:5432/tars_test",
)


# ---------------------------------------------------------------------------
# Fast synchronous connectivity check at import time.
# If PostgreSQL is unreachable, skip ALL tests in this package immediately
# instead of waiting 3s × 32 tests.
# ---------------------------------------------------------------------------
def _pg_is_reachable(host: str = "localhost", port: int = 5432, timeout: float = 2.0) -> bool:
    """Synchronous TCP check -- no asyncpg, no driver, just a socket probe."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (OSError, ConnectionRefusedError, TimeoutError):
        return False


# Parse host/port from TEST_DATABASE_URL for the socket check
_pg_host = "localhost"
_pg_port = 5432
try:
    _at_part = TEST_DATABASE_URL.split("@")[1]  # tars:tars@localhost:5432/tars_test
    _host_port = _at_part.split("/")[0]          # localhost:5432
    if ":" in _host_port:
        _pg_host, _pg_port_str = _host_port.rsplit(":", 1)
        _pg_port = int(_pg_port_str)
    else:
        _pg_host = _host_port
except (IndexError, ValueError):
    pass

_PG_AVAILABLE = _pg_is_reachable(_pg_host, _pg_port)


@pytest.fixture(autouse=True)
def _require_postgres():
    """Skip every test in the phase2 package if PostgreSQL is not reachable."""
    if not _PG_AVAILABLE:
        pytest.skip(f"PostgreSQL not reachable at {_pg_host}:{_pg_port}")


# ---------------------------------------------------------------------------
# Ensure the test database exists (create it if needed)
# ---------------------------------------------------------------------------
async def _ensure_test_db_exists():
    """Create the tars_test database if it doesn't exist."""
    admin_url = TEST_DATABASE_URL.rsplit("/", 1)[0] + "/tars"
    engine = create_async_engine(
        admin_url,
        isolation_level="AUTOCOMMIT",
        connect_args={"timeout": 3},
    )
    try:
        async with engine.connect() as conn:
            result = await conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = 'tars_test'")
            )
            if result.scalar() is None:
                await conn.execute(text("CREATE DATABASE tars_test"))
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# Sample mission data matching Phase 1 MissionTelemetry schema
# ---------------------------------------------------------------------------
def make_sample_mission(
    mission_id: str = "test_mission_001",
    num_snapshots: int = 5,
    num_faults: int = 1,
) -> dict:
    """Build a valid Phase 1 MissionTelemetry dict for testing."""
    start = datetime(2026, 6, 8, 6, 30, 0, tzinfo=timezone.utc)

    telemetry = []
    for i in range(num_snapshots):
        ts = start + timedelta(seconds=i)
        telemetry.append({
            "timestamp": ts.isoformat(),
            "position": {
                "latitude_deg": 47.3977 + i * 0.0001,
                "longitude_deg": 8.5456 + i * 0.0001,
                "absolute_altitude_m": 488.0 + i,
                "relative_altitude_m": 20.0 + i * 0.5,
            },
            "velocity": {
                "north_m_s": 2.0 + i * 0.1,
                "east_m_s": 1.0,
                "down_m_s": -0.1,
            },
            "battery": {
                "voltage_v": 12.0 - i * 0.1,
                "remaining_percent": 95.0 - i * 2.0,
            },
            "gps": {
                "num_satellites": 12,
                "fix_type": "FIX_3D",
            },
            "attitude": {
                "roll_deg": 1.0 + i * 0.1,
                "pitch_deg": -0.5,
                "yaw_deg": 90.0 + i,
            },
            "flight_mode": "MISSION",
            "health": {
                "is_gyrometer_calibration_ok": True,
                "is_accelerometer_calibration_ok": True,
                "is_magnetometer_calibration_ok": True,
                "is_home_position_ok": True,
                "is_global_position_ok": True,
            },
        })

    faults = []
    if num_faults > 0:
        faults.append({
            "fault_type": "gps_block",
            "triggered_at": (start + timedelta(seconds=2)).isoformat(),
            "parameters": {"duration_s": 5},
            "description": "GPS signal blocked for 5 seconds",
        })

    return {
        "mission_id": mission_id,
        "drone_id": "tars-sim-01",
        "start_time": start.isoformat(),
        "end_time": (start + timedelta(seconds=num_snapshots - 1)).isoformat(),
        "faults_injected": faults,
        "telemetry": telemetry,
        "mission_result": "SUCCESS",
        "summary": {
            "total_snapshots": num_snapshots,
            "duration_seconds": float(num_snapshots - 1),
            "max_altitude_m": 20.0 + (num_snapshots - 1) * 0.5,
            "distance_traveled_m": 50.0,
            "min_battery_percent": 95.0 - (num_snapshots - 1) * 2.0,
            "max_speed_m_s": 2.0 + (num_snapshots - 1) * 0.1,
            "collection_rate_hz": 1.0,
        },
    }


@pytest.fixture
def sample_mission_data() -> dict:
    """Return a valid Phase 1 MissionTelemetry dict."""
    return make_sample_mission()


@pytest.fixture
def sample_mission_file(sample_mission_data: dict) -> str:
    """Write sample mission data to a temp file and return the path."""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, dir="."
    ) as f:
        json.dump(sample_mission_data, f)
        return f.name


# ---------------------------------------------------------------------------
# Database fixtures
# ---------------------------------------------------------------------------
@pytest_asyncio.fixture
async def db_engine():
    """
    Create a test database engine and tables.

    Uses tars_test database (separate from production tars).
    The pytestmark above already skips if PostgreSQL is unreachable,
    so this fixture only runs when connectivity is confirmed.
    """
    # Ensure tars_test database exists
    await _ensure_test_db_exists()

    engine = create_async_engine(
        TEST_DATABASE_URL,
        echo=False,
        connect_args={"timeout": 5},
    )

    # Create all tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    # Drop all tables after tests
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine) -> AsyncSession:
    """Yield a database session for testing."""
    session_factory = async_sessionmaker(
        db_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with session_factory() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture
async def client(db_engine):
    """
    Yield an httpx AsyncClient wired to the FastAPI app with test DB.

    Overrides both the session dependency and the health check
    to use the test database engine.
    """
    session_factory = async_sessionmaker(
        db_engine, class_=AsyncSession, expire_on_commit=False
    )

    async def override_get_session():
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    async def override_check_database() -> bool:
        try:
            async with db_engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            return True
        except Exception:
            return False

    app.dependency_overrides[get_session] = override_get_session

    # Monkey-patch check_database for health endpoint
    import tars.phase2.api as api_module
    original_check = api_module.check_database
    api_module.check_database = override_check_database

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()
    api_module.check_database = original_check
