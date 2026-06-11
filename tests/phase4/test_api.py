"""
Tests for Phase 4 Incident Engine API
=======================================
Tests FastAPI endpoints using httpx AsyncClient with mocked state client.

Redis tests use DB 15 and skip if Redis is unavailable.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from tars.phase4.api import app, get_service
from tars.phase4.models import (
    IncidentType,
    ProcessingStatus,
    Severity,
)
from tars.phase4.service import IncidentService
from tars.phase4.state_client import StateClient
from tars.phase4.store import IncidentStore

from .conftest import (
    make_gps_degraded_states,
    make_nominal_states,
    requires_redis,
    _TEST_REDIS_URL,
)


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def require_redis_for_api():
    """Skip API tests if Redis is not available."""
    import socket
    try:
        with socket.create_connection(("localhost", 6379), timeout=2.0):
            pass
    except OSError:
        pytest.skip("Redis not available on localhost:6379")


@pytest_asyncio.fixture
async def api_client(require_redis_for_api):
    """
    Create an async test client with real Redis (DB 15) and mocked state client.
    """
    store = IncidentStore(redis_url=_TEST_REDIS_URL)
    await store.connect()

    # Mock state client to avoid needing Phase 3 API running
    mock_state_client = AsyncMock(spec=StateClient)
    mock_state_client.health_check = AsyncMock(return_value=True)

    service = IncidentService(store=store, state_client=mock_state_client)

    # Patch module-level state
    import tars.phase4.api as api_module
    original_store = api_module._store
    original_service = api_module._service
    original_state_client = api_module._state_client
    api_module._store = store
    api_module._service = service
    api_module._state_client = mock_state_client

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, mock_state_client

    # Cleanup
    await store.redis.flushdb()
    await store.close()
    api_module._store = original_store
    api_module._service = original_service
    api_module._state_client = original_state_client


# =============================================================================
# Health Endpoint
# =============================================================================

class TestHealthEndpoint:
    """Test GET /health."""

    @pytest.mark.asyncio
    async def test_health_ok(self, api_client):
        client, _ = api_client
        response = await client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["redis"] == "ok"
        # Phase 3 is mocked to return True for health_check
        assert data["phase3"] == "ok"


# =============================================================================
# Process Endpoint
# =============================================================================

class TestProcessEndpoint:
    """Test POST /api/v1/incidents/process/{mission_id}."""

    @pytest.mark.asyncio
    async def test_process_nominal_mission(self, api_client):
        client, mock_state_client = api_client
        mock_state_client.get_timeline = AsyncMock(return_value={
            "mission_id": "test_mission",
            "states": make_nominal_states(10),
            "total": 10,
        })

        response = await client.post(
            "/api/v1/incidents/process/test_mission",
            json={},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["mission_id"] == "test_mission"
        assert data["states_evaluated"] == 10
        assert data["incidents_detected"] == 0
        assert data["status"] == "complete"

    @pytest.mark.asyncio
    async def test_process_degraded_mission(self, api_client):
        client, mock_state_client = api_client
        mock_state_client.get_timeline = AsyncMock(return_value={
            "mission_id": "test_mission",
            "states": make_gps_degraded_states(5),
            "total": 5,
        })

        response = await client.post(
            "/api/v1/incidents/process/test_mission",
            json={},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["incidents_detected"] >= 1

    @pytest.mark.asyncio
    async def test_process_with_time_range(self, api_client):
        client, mock_state_client = api_client
        mock_state_client.get_timeline = AsyncMock(return_value={
            "mission_id": "test_mission",
            "states": make_nominal_states(5),
            "total": 5,
        })

        response = await client.post(
            "/api/v1/incidents/process/test_mission",
            json={"from_ms": 5000, "to_ms": 30000},
        )
        assert response.status_code == 200


# =============================================================================
# List Incidents Endpoint
# =============================================================================

class TestListIncidentsEndpoint:
    """Test GET /api/v1/incidents/{mission_id}."""

    @pytest.mark.asyncio
    async def test_list_after_processing(self, api_client):
        client, mock_state_client = api_client
        mock_state_client.get_timeline = AsyncMock(return_value={
            "mission_id": "test_mission",
            "states": make_gps_degraded_states(5),
            "total": 5,
        })

        # Process first
        await client.post(
            "/api/v1/incidents/process/test_mission",
            json={},
        )

        # Then list
        response = await client.get("/api/v1/incidents/test_mission")
        assert response.status_code == 200
        data = response.json()
        assert data["mission_id"] == "test_mission"
        assert data["total"] >= 1
        assert len(data["incidents"]) >= 1

    @pytest.mark.asyncio
    async def test_list_empty(self, api_client):
        client, _ = api_client
        response = await client.get("/api/v1/incidents/nonexistent")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 0
        assert data["incidents"] == []

    @pytest.mark.asyncio
    async def test_list_with_time_range(self, api_client):
        client, mock_state_client = api_client
        mock_state_client.get_timeline = AsyncMock(return_value={
            "mission_id": "test_mission",
            "states": make_gps_degraded_states(5),
            "total": 5,
        })

        await client.post(
            "/api/v1/incidents/process/test_mission",
            json={},
        )

        response = await client.get(
            "/api/v1/incidents/test_mission",
            params={"from_ms": 0, "to_ms": 100000},
        )
        assert response.status_code == 200


# =============================================================================
# Get Incident Endpoint
# =============================================================================

class TestGetIncidentEndpoint:
    """Test GET /api/v1/incidents/{mission_id}/{incident_id}."""

    @pytest.mark.asyncio
    async def test_get_existing_incident(self, api_client):
        client, mock_state_client = api_client
        mock_state_client.get_timeline = AsyncMock(return_value={
            "mission_id": "test_mission",
            "states": make_gps_degraded_states(5),
            "total": 5,
        })

        await client.post(
            "/api/v1/incidents/process/test_mission",
            json={},
        )

        # Get the list to find an incident ID
        list_response = await client.get("/api/v1/incidents/test_mission")
        incidents = list_response.json()["incidents"]
        assert len(incidents) >= 1

        incident_id = incidents[0]["incident_id"]
        response = await client.get(
            f"/api/v1/incidents/test_mission/{incident_id}"
        )
        assert response.status_code == 200
        data = response.json()
        assert data["incident_id"] == incident_id

    @pytest.mark.asyncio
    async def test_get_nonexistent_incident(self, api_client):
        client, _ = api_client
        response = await client.get(
            "/api/v1/incidents/test_mission/inc_nonexistent"
        )
        assert response.status_code == 404


# =============================================================================
# Processing Status Endpoint
# =============================================================================

class TestProcessingStatusEndpoint:
    """Test GET /api/v1/incidents/{mission_id}/status."""

    @pytest.mark.asyncio
    async def test_status_after_processing(self, api_client):
        client, mock_state_client = api_client
        mock_state_client.get_timeline = AsyncMock(return_value={
            "mission_id": "test_mission",
            "states": make_nominal_states(10),
            "total": 10,
        })

        await client.post(
            "/api/v1/incidents/process/test_mission",
            json={},
        )

        response = await client.get(
            "/api/v1/incidents/test_mission/status"
        )
        assert response.status_code == 200
        data = response.json()
        assert data["mission_id"] == "test_mission"
        assert data["status"] == "complete"
        assert data["states_evaluated"] == 10

    @pytest.mark.asyncio
    async def test_status_not_started(self, api_client):
        client, _ = api_client
        response = await client.get(
            "/api/v1/incidents/nonexistent/status"
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "not_started"
