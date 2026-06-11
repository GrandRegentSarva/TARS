"""
Tests for Phase 5 Reasoning Service
=====================================
Tests reasoning orchestration: analyze, overwrite, get, list.

Uses fake provider and real Redis (DB 15) for integration tests.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
import pytest_asyncio

from tars.phase5.incident_client import IncidentClient
from tars.phase5.models import ReasoningAnalysis, ReasoningResult
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

@pytest_asyncio.fixture
async def service_components():
    """Create service with fake provider and real Redis (DB 15)."""
    import socket
    try:
        with socket.create_connection(("localhost", 6379), timeout=2.0):
            pass
    except OSError:
        pytest.skip("Redis not available on localhost:6379")

    store = ReasoningStore(redis_url=_TEST_REDIS_URL)
    await store.connect()

    mock_client = AsyncMock(spec=IncidentClient)
    fake_provider = FakeReasoningProvider()

    service = ReasoningService(
        store=store,
        incident_client=mock_client,
        provider=fake_provider,
    )

    yield service, mock_client, fake_provider, store

    await store.redis.flushdb()
    await store.close()


# =============================================================================
# Analyze Tests
# =============================================================================

@requires_redis
class TestAnalyzeIncident:
    """Test incident analysis orchestration."""

    @pytest.mark.asyncio
    async def test_analyze_new_incident(self, service_components):
        service, mock_client, provider, store = service_components
        incident = make_incident()
        mock_client.get_incident = AsyncMock(return_value=incident)

        result = await service.analyze_incident(
            "test_mission", "inc_test123", overwrite=True
        )

        assert isinstance(result, ReasoningResult)
        assert result.mission_id == "test_mission"
        assert result.incident_id == "inc_test123"
        assert result.incident_type == "navigation_instability"
        assert result.root_cause == "gps_interference"
        assert result.advisory_only is True
        assert result.model == "fake-gemini-test"
        assert result.prompt_version == "1.0.0"
        assert provider.call_count == 1

    @pytest.mark.asyncio
    async def test_analyze_persists_result(self, service_components):
        service, mock_client, provider, store = service_components
        incident = make_incident()
        mock_client.get_incident = AsyncMock(return_value=incident)

        await service.analyze_incident(
            "test_mission", "inc_test123", overwrite=True
        )

        persisted = await store.get_analysis("test_mission", "inc_test123")
        assert persisted is not None
        assert persisted.root_cause == "gps_interference"

    @pytest.mark.asyncio
    async def test_overwrite_false_returns_existing(self, service_components):
        service, mock_client, provider, store = service_components
        incident = make_incident()
        mock_client.get_incident = AsyncMock(return_value=incident)

        # First analysis
        first = await service.analyze_incident(
            "test_mission", "inc_test123", overwrite=True
        )
        assert provider.call_count == 1

        # Second with overwrite=false should return existing
        second = await service.analyze_incident(
            "test_mission", "inc_test123", overwrite=False
        )
        assert provider.call_count == 1  # Not called again
        assert second.reasoning_id == first.reasoning_id

    @pytest.mark.asyncio
    async def test_overwrite_true_replaces(self, service_components):
        service, mock_client, provider, store = service_components
        incident = make_incident()
        mock_client.get_incident = AsyncMock(return_value=incident)

        first = await service.analyze_incident(
            "test_mission", "inc_test123", overwrite=True
        )
        second = await service.analyze_incident(
            "test_mission", "inc_test123", overwrite=True
        )

        assert provider.call_count == 2
        assert second.reasoning_id != first.reasoning_id

        # Only the latest should be persisted
        persisted = await store.get_analysis("test_mission", "inc_test123")
        assert persisted is not None
        assert persisted.reasoning_id == second.reasoning_id

    @pytest.mark.asyncio
    async def test_failed_provider_does_not_persist(self, service_components):
        service, mock_client, _, store = service_components
        incident = make_incident()
        mock_client.get_incident = AsyncMock(return_value=incident)

        # Replace provider with failing one
        failing_provider = FakeReasoningProvider(
            fail=True, fail_message="Provider error"
        )
        service._provider = failing_provider

        with pytest.raises(ValueError, match="Provider error"):
            await service.analyze_incident(
                "test_mission", "inc_test123", overwrite=True
            )

        # Nothing should be persisted
        persisted = await store.get_analysis("test_mission", "inc_test123")
        assert persisted is None

    @pytest.mark.asyncio
    async def test_preserves_model_metadata(self, service_components):
        service, mock_client, provider, store = service_components
        incident = make_incident()
        mock_client.get_incident = AsyncMock(return_value=incident)

        result = await service.analyze_incident(
            "test_mission", "inc_test123", overwrite=True
        )

        assert result.model == provider.model_name
        assert result.prompt_version == "1.0.0"
        assert result.created_at is not None
        assert len(result.reasoning_id) > 0

    @pytest.mark.asyncio
    async def test_battery_incident_analysis(self, service_components):
        service, mock_client, provider, store = service_components
        incident = make_battery_incident()
        mock_client.get_incident = AsyncMock(return_value=incident)

        result = await service.analyze_incident(
            "test_mission", "inc_battery_001", overwrite=True
        )

        assert result.incident_type == "battery_degradation"
        assert result.root_cause == "accelerated_discharge"


# =============================================================================
# Get and List Tests
# =============================================================================

@requires_redis
class TestGetAndList:
    """Test analysis retrieval and listing."""

    @pytest.mark.asyncio
    async def test_get_existing(self, service_components):
        service, mock_client, provider, store = service_components
        incident = make_incident()
        mock_client.get_incident = AsyncMock(return_value=incident)

        await service.analyze_incident(
            "test_mission", "inc_test123", overwrite=True
        )

        result = await service.get_analysis("test_mission", "inc_test123")
        assert result is not None
        assert result.incident_id == "inc_test123"

    @pytest.mark.asyncio
    async def test_get_nonexistent(self, service_components):
        service, _, _, _ = service_components
        result = await service.get_analysis("test_mission", "inc_nope")
        assert result is None

    @pytest.mark.asyncio
    async def test_list_analyses(self, service_components):
        service, mock_client, provider, store = service_components

        inc1 = make_incident(incident_id="inc_1")
        inc2 = make_battery_incident(incident_id="inc_2")
        mock_client.get_incident = AsyncMock(side_effect=[inc1, inc2])

        await service.analyze_incident(
            "test_mission", "inc_1", overwrite=True
        )
        await service.analyze_incident(
            "test_mission", "inc_2", overwrite=True
        )

        response = await service.list_analyses("test_mission")
        assert response.total == 2
        assert len(response.analyses) == 2
        assert response.mission_id == "test_mission"

    @pytest.mark.asyncio
    async def test_list_empty(self, service_components):
        service, _, _, _ = service_components
        response = await service.list_analyses("nonexistent")
        assert response.total == 0
        assert response.analyses == []
