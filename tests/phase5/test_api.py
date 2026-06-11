"""
Tests for Phase 5 Reasoning API
=================================
Tests FastAPI endpoints using httpx AsyncClient with mocked incident client
and fake reasoning provider.

Redis tests use DB 15 and skip if Redis is unavailable.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

import httpx

from tars.phase5.api import app
from tars.phase5.incident_client import IncidentClient
from tars.phase5.provider import FakeReasoningProvider
from tars.phase5.service import ReasoningService
from tars.phase5.store import ReasoningStore

from .conftest import (
    _TEST_REDIS_URL,
    make_incident,
    make_battery_incident,
    requires_redis,
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
    Create an async test client with real Redis (DB 15),
    mocked incident client, and fake reasoning provider.
    """
    store = ReasoningStore(redis_url=_TEST_REDIS_URL)
    await store.connect()

    mock_incident_client = AsyncMock(spec=IncidentClient)
    mock_incident_client.health_check = AsyncMock(return_value=True)

    fake_provider = FakeReasoningProvider()

    service = ReasoningService(
        store=store,
        incident_client=mock_incident_client,
        provider=fake_provider,
    )

    # Patch module-level state
    import tars.phase5.api as api_module
    original_store = api_module._store
    original_service = api_module._service
    original_incident_client = api_module._incident_client
    original_provider = api_module._provider
    api_module._store = store
    api_module._service = service
    api_module._incident_client = mock_incident_client
    api_module._provider = fake_provider

    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://test"
    ) as client:
        yield client, mock_incident_client, fake_provider

    # Cleanup
    await store.redis.flushdb()
    await store.close()
    api_module._store = original_store
    api_module._service = original_service
    api_module._incident_client = original_incident_client
    api_module._provider = original_provider


# =============================================================================
# Health Endpoint
# =============================================================================

class TestHealthEndpoint:
    """Test GET /health."""

    @pytest.mark.asyncio
    async def test_health_ok(self, api_client):
        client, _, _ = api_client
        response = await client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["redis"] == "ok"
        assert data["phase4"] == "ok"
        assert data["gemini"] == "ok"


# =============================================================================
# Analyze Endpoint
# =============================================================================

class TestAnalyzeEndpoint:
    """Test POST /api/v1/reasoning/analyze/{mission_id}/{incident_id}."""

    @pytest.mark.asyncio
    async def test_analyze_incident(self, api_client):
        client, mock_incident_client, _ = api_client
        incident = make_incident()
        mock_incident_client.get_incident = AsyncMock(return_value=incident)

        response = await client.post(
            "/api/v1/reasoning/analyze/test_mission/inc_test123",
            json={"overwrite": True},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["mission_id"] == "test_mission"
        assert data["incident_id"] == "inc_test123"
        assert data["incident_type"] == "navigation_instability"
        assert data["root_cause"] == "gps_interference"
        assert data["advisory_only"] is True
        assert 0.0 <= data["confidence"] <= 1.0
        assert len(data["recommendation"]) > 0
        assert len(data["rationale"]) > 0
        assert data["model"] == "fake-gemini-test"
        assert data["prompt_version"] == "1.0.0"

    @pytest.mark.asyncio
    async def test_analyze_default_overwrite(self, api_client):
        """Default request body should have overwrite=true."""
        client, mock_incident_client, _ = api_client
        incident = make_incident()
        mock_incident_client.get_incident = AsyncMock(return_value=incident)

        response = await client.post(
            "/api/v1/reasoning/analyze/test_mission/inc_test123",
            json={},
        )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_analyze_overwrite_false_returns_existing(self, api_client):
        client, mock_incident_client, provider = api_client
        incident = make_incident()
        mock_incident_client.get_incident = AsyncMock(return_value=incident)

        # First analysis
        r1 = await client.post(
            "/api/v1/reasoning/analyze/test_mission/inc_test123",
            json={"overwrite": True},
        )
        assert r1.status_code == 200
        first_id = r1.json()["reasoning_id"]

        # Second with overwrite=false
        r2 = await client.post(
            "/api/v1/reasoning/analyze/test_mission/inc_test123",
            json={"overwrite": False},
        )
        assert r2.status_code == 200
        assert r2.json()["reasoning_id"] == first_id

    @pytest.mark.asyncio
    async def test_analyze_404_from_phase4(self, api_client):
        client, mock_incident_client, _ = api_client
        mock_incident_client.get_incident = AsyncMock(
            side_effect=httpx.HTTPStatusError(
                "Not found",
                request=httpx.Request(
                    "GET", "http://test:8003/api/v1/incidents/m/i"
                ),
                response=httpx.Response(status_code=404),
            )
        )

        response = await client.post(
            "/api/v1/reasoning/analyze/test_mission/inc_nonexistent",
            json={"overwrite": True},
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_analyze_502_from_phase4(self, api_client):
        client, mock_incident_client, _ = api_client
        mock_incident_client.get_incident = AsyncMock(
            side_effect=httpx.HTTPStatusError(
                "Server error",
                request=httpx.Request(
                    "GET", "http://test:8003/api/v1/incidents/m/i"
                ),
                response=httpx.Response(status_code=500),
            )
        )

        response = await client.post(
            "/api/v1/reasoning/analyze/test_mission/inc_test123",
            json={"overwrite": True},
        )
        assert response.status_code == 502

    @pytest.mark.asyncio
    async def test_analyze_phase4_unreachable(self, api_client):
        client, mock_incident_client, _ = api_client
        mock_incident_client.get_incident = AsyncMock(
            side_effect=httpx.ConnectError("Connection refused")
        )

        response = await client.post(
            "/api/v1/reasoning/analyze/test_mission/inc_test123",
            json={"overwrite": True},
        )
        assert response.status_code == 502

    @pytest.mark.asyncio
    async def test_analyze_provider_failure(self, api_client):
        client, mock_incident_client, _ = api_client
        incident = make_incident()
        mock_incident_client.get_incident = AsyncMock(return_value=incident)

        # Patch the service's provider to a failing one
        import tars.phase5.api as api_module
        service = api_module._service
        original_provider = service._provider
        service._provider = FakeReasoningProvider(
            fail=True, fail_message="Model error"
        )

        response = await client.post(
            "/api/v1/reasoning/analyze/test_mission/inc_test123",
            json={"overwrite": True},
        )
        assert response.status_code == 502

        service._provider = original_provider

    @pytest.mark.asyncio
    async def test_analyze_unconfigured_provider(self, api_client):
        client, mock_incident_client, _ = api_client

        # Patch the module-level provider to unconfigured
        import tars.phase5.api as api_module
        original_provider = api_module._provider
        api_module._provider = FakeReasoningProvider(configured=False)

        response = await client.post(
            "/api/v1/reasoning/analyze/test_mission/inc_test123",
            json={"overwrite": True},
        )
        assert response.status_code == 503

        api_module._provider = original_provider

    @pytest.mark.asyncio
    async def test_cached_analysis_returned_when_provider_unconfigured(self, api_client):
        """overwrite=false should return cached analysis even when Gemini is unconfigured."""
        client, mock_incident_client, _ = api_client
        incident = make_incident()
        mock_incident_client.get_incident = AsyncMock(return_value=incident)

        # First: create an analysis with a configured provider
        r1 = await client.post(
            "/api/v1/reasoning/analyze/test_mission/inc_test123",
            json={"overwrite": True},
        )
        assert r1.status_code == 200
        first_id = r1.json()["reasoning_id"]

        # Now switch to an unconfigured provider
        import tars.phase5.api as api_module
        original_provider = api_module._provider
        api_module._provider = FakeReasoningProvider(configured=False)

        # overwrite=false should return the cached result, not 503
        r2 = await client.post(
            "/api/v1/reasoning/analyze/test_mission/inc_test123",
            json={"overwrite": False},
        )
        assert r2.status_code == 200
        assert r2.json()["reasoning_id"] == first_id

        # overwrite=true should still fail with 503
        r3 = await client.post(
            "/api/v1/reasoning/analyze/test_mission/inc_test123",
            json={"overwrite": True},
        )
        assert r3.status_code == 503

        api_module._provider = original_provider


# =============================================================================
# Get Analysis Endpoint
# =============================================================================

class TestGetAnalysisEndpoint:
    """Test GET /api/v1/reasoning/{mission_id}/{incident_id}."""

    @pytest.mark.asyncio
    async def test_get_existing(self, api_client):
        client, mock_incident_client, _ = api_client
        incident = make_incident()
        mock_incident_client.get_incident = AsyncMock(return_value=incident)

        # Create analysis first
        await client.post(
            "/api/v1/reasoning/analyze/test_mission/inc_test123",
            json={"overwrite": True},
        )

        response = await client.get(
            "/api/v1/reasoning/test_mission/inc_test123"
        )
        assert response.status_code == 200
        data = response.json()
        assert data["incident_id"] == "inc_test123"
        assert data["advisory_only"] is True

    @pytest.mark.asyncio
    async def test_get_nonexistent(self, api_client):
        client, _, _ = api_client
        response = await client.get(
            "/api/v1/reasoning/test_mission/inc_nonexistent"
        )
        assert response.status_code == 404


# =============================================================================
# List Analyses Endpoint
# =============================================================================

class TestListAnalysesEndpoint:
    """Test GET /api/v1/reasoning/{mission_id}."""

    @pytest.mark.asyncio
    async def test_list_after_analysis(self, api_client):
        client, mock_incident_client, _ = api_client
        incident = make_incident()
        mock_incident_client.get_incident = AsyncMock(return_value=incident)

        await client.post(
            "/api/v1/reasoning/analyze/test_mission/inc_test123",
            json={"overwrite": True},
        )

        response = await client.get("/api/v1/reasoning/test_mission")
        assert response.status_code == 200
        data = response.json()
        assert data["mission_id"] == "test_mission"
        assert data["total"] >= 1
        assert len(data["analyses"]) >= 1

    @pytest.mark.asyncio
    async def test_list_empty(self, api_client):
        client, _, _ = api_client
        response = await client.get("/api/v1/reasoning/nonexistent")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 0
        assert data["analyses"] == []

    @pytest.mark.asyncio
    async def test_list_multiple_incidents(self, api_client):
        client, mock_incident_client, _ = api_client

        inc1 = make_incident(incident_id="inc_1")
        inc2 = make_battery_incident(incident_id="inc_2")
        mock_incident_client.get_incident = AsyncMock(
            side_effect=[inc1, inc2]
        )

        await client.post(
            "/api/v1/reasoning/analyze/test_mission/inc_1",
            json={"overwrite": True},
        )
        await client.post(
            "/api/v1/reasoning/analyze/test_mission/inc_2",
            json={"overwrite": True},
        )

        response = await client.get("/api/v1/reasoning/test_mission")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 2
