"""
API Tests
=========
Tests for the Phase 3 FastAPI endpoints.

These tests use a mock ReplayClient and a real Redis store (DB 15).
They are automatically skipped if Redis is not reachable.

Coverage:
- Health endpoint returns ok with Redis status
- Process endpoint triggers state computation
- Current state endpoint returns latest snapshot
- Timeline endpoint returns ordered snapshots
- State-at-time endpoint returns nearest prior snapshot
- Processing status endpoint returns metadata
- 404 for missing mission state
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from tars.phase3.api import app, _store, _service
from tars.phase3.models import (
    MissionPhase,
    HealthStatus,
    ProcessingStatus,
    ReplayData,
    StateSnapshot,
    SignalIndicators,
    StateMetrics,
    TelemetryFrame,
)
from tars.phase3.replay_client import ReplayClient
from tars.phase3.service import StateService
from tars.phase3.store import StateStore

from .conftest import (
    TEST_REDIS_URL,
    _REDIS_AVAILABLE,
    make_replay_data,
    make_replay_frames,
)


pytestmark = pytest.mark.asyncio


@pytest.fixture
def require_redis_for_api():
    """Skip API tests if Redis is not reachable."""
    if not _REDIS_AVAILABLE:
        pytest.skip("Redis not reachable at localhost:6379")


@pytest_asyncio.fixture
async def api_client(require_redis_for_api):
    """
    Yield an httpx AsyncClient wired to the Phase 3 FastAPI app.

    Uses test Redis DB 15 and a mock ReplayClient.
    """
    import tars.phase3.api as api_module

    # Create test store
    store = StateStore(redis_url=TEST_REDIS_URL)
    await store.connect()
    await store.redis.flushdb()

    # Create mock replay client
    mock_replay_client = AsyncMock(spec=ReplayClient)
    mock_replay_client.fetch_replay = AsyncMock(
        return_value=make_replay_data(num_frames=5)
    )

    # Create service with test store and mock client
    service = StateService(store=store, replay_client=mock_replay_client)

    # Override module-level state
    original_store = api_module._store
    original_service = api_module._service
    api_module._store = store
    api_module._service = service

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    # Cleanup
    await store.redis.flushdb()
    await store.close()
    api_module._store = original_store
    api_module._service = original_service


class TestHealthEndpoint:
    """Test GET /health."""

    async def test_health_ok(self, api_client):
        """Health endpoint returns ok with Redis status."""
        resp = await api_client.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["redis"] == "ok"


class TestProcessEndpoint:
    """Test POST /api/v1/state/process/{mission_id}."""

    async def test_process_mission(self, api_client):
        """Process endpoint triggers state computation."""
        resp = await api_client.post(
            "/api/v1/state/process/test_mission_001",
            json={"overwrite": True},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["mission_id"] == "test_mission_001"
        assert body["frames_processed"] == 5
        assert body["frames_failed"] == 0
        assert body["states_written"] == 5
        assert body["status"] == "complete"

    async def test_process_with_defaults(self, api_client):
        """Process endpoint works with default request body."""
        resp = await api_client.post(
            "/api/v1/state/process/test_mission_001",
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "complete"


class TestCurrentStateEndpoint:
    """Test GET /api/v1/state/{mission_id}/current."""

    async def test_get_current_state(self, api_client):
        """Current state returns latest snapshot after processing."""
        # First process the mission
        await api_client.post(
            "/api/v1/state/process/test_mission_001",
            json={"overwrite": True},
        )

        resp = await api_client.get("/api/v1/state/test_mission_001/current")
        assert resp.status_code == 200
        body = resp.json()
        assert body["mission_id"] == "test_mission_001"
        assert "phase" in body
        assert "health" in body
        assert "risk" in body
        assert "signals" in body
        assert "metrics" in body

    async def test_current_state_not_found(self, api_client):
        """Current state returns 404 for unprocessed mission."""
        resp = await api_client.get("/api/v1/state/nonexistent/current")
        assert resp.status_code == 404


class TestTimelineEndpoint:
    """Test GET /api/v1/state/{mission_id}/timeline."""

    async def test_get_timeline(self, api_client):
        """Timeline returns ordered snapshots after processing."""
        await api_client.post(
            "/api/v1/state/process/test_mission_001",
            json={"overwrite": True},
        )

        resp = await api_client.get("/api/v1/state/test_mission_001/timeline")
        assert resp.status_code == 200
        body = resp.json()
        assert body["mission_id"] == "test_mission_001"
        assert body["total"] == 5
        assert len(body["states"]) == 5

        # Verify ordering
        for i in range(len(body["states"]) - 1):
            assert body["states"][i]["elapsed_ms"] <= body["states"][i + 1]["elapsed_ms"]

    async def test_timeline_with_range(self, api_client):
        """Timeline with from_ms and to_ms filters correctly."""
        await api_client.post(
            "/api/v1/state/process/test_mission_001",
            json={"overwrite": True},
        )

        resp = await api_client.get(
            "/api/v1/state/test_mission_001/timeline?from_ms=1000&to_ms=3000"
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 3  # 1000, 2000, 3000

    async def test_empty_timeline(self, api_client):
        """Timeline for unprocessed mission returns empty list."""
        resp = await api_client.get("/api/v1/state/nonexistent/timeline")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 0
        assert body["states"] == []


class TestStateAtEndpoint:
    """Test GET /api/v1/state/{mission_id}/at/{elapsed_ms}."""

    async def test_state_at_exact_time(self, api_client):
        """State at exact elapsed_ms returns that snapshot."""
        await api_client.post(
            "/api/v1/state/process/test_mission_001",
            json={"overwrite": True},
        )

        resp = await api_client.get("/api/v1/state/test_mission_001/at/2000")
        assert resp.status_code == 200
        body = resp.json()
        assert body["elapsed_ms"] == 2000

    async def test_state_at_between_times(self, api_client):
        """State at time between snapshots returns nearest prior."""
        await api_client.post(
            "/api/v1/state/process/test_mission_001",
            json={"overwrite": True},
        )

        resp = await api_client.get("/api/v1/state/test_mission_001/at/2500")
        assert resp.status_code == 200
        body = resp.json()
        assert body["elapsed_ms"] == 2000  # Nearest prior

    async def test_state_at_not_found(self, api_client):
        """State at time for unprocessed mission returns 404."""
        resp = await api_client.get("/api/v1/state/nonexistent/at/1000")
        assert resp.status_code == 404


class TestProcessingStatusEndpoint:
    """Test GET /api/v1/state/{mission_id}/status."""

    async def test_status_after_processing(self, api_client):
        """Status returns complete after successful processing."""
        await api_client.post(
            "/api/v1/state/process/test_mission_001",
            json={"overwrite": True},
        )

        resp = await api_client.get("/api/v1/state/test_mission_001/status")
        assert resp.status_code == 200
        body = resp.json()
        assert body["mission_id"] == "test_mission_001"
        assert body["status"] == "complete"
        assert body["frames_processed"] == 5

    async def test_status_not_started(self, api_client):
        """Status for unprocessed mission returns not_started."""
        resp = await api_client.get("/api/v1/state/nonexistent/status")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "not_started"
