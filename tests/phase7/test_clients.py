"""
Phase 7 Client Tests
=====================
Tests for Phase 2, Phase 4, and Phase 5 HTTP clients.

Uses httpx mock transport to simulate upstream API responses
and exercises the actual client classes.
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, patch, MagicMock

import httpx
import pytest
import pytest_asyncio

from tars.phase7.phase2_client import (
    Phase2Client,
    Phase2ClientError,
    Phase2NotFoundError,
    Phase2UnavailableError,
)
from tars.phase7.phase4_client import (
    Phase4Client,
    Phase4ClientError,
    Phase4UnavailableError,
)
from tars.phase7.phase5_client import (
    Phase5Client,
    Phase5ClientError,
    Phase5UnavailableError,
)

from .conftest import make_incident, make_mission, make_reasoning


# =============================================================================
# Mock Transport Helper
# =============================================================================

class MockTransport(httpx.AsyncBaseTransport):
    """Mock transport that returns predefined responses."""

    def __init__(self, responses: dict[str, tuple[int, Any]]):
        self._responses = responses

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path in self._responses:
            status, body = self._responses[path]
            return httpx.Response(
                status_code=status,
                json=body,
                request=request,
            )
        return httpx.Response(status_code=404, json={"detail": "Not found"}, request=request)


class ErrorTransport(httpx.AsyncBaseTransport):
    """Mock transport that raises connection errors."""

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Connection refused")


def _patch_httpx_client(module_path: str, transport: httpx.AsyncBaseTransport):
    """
    Create a patch context that replaces httpx.AsyncClient in the given module
    with a version that uses the provided transport.

    The key insight: we need the patched class, when called as a constructor,
    to return an object that works as an async context manager and uses our
    transport for actual HTTP handling.
    """
    real_client = httpx.AsyncClient(transport=transport, base_url="http://mock")

    mock_cls = MagicMock()
    # When the patched AsyncClient(...) is called, return our real client
    mock_cls.return_value = real_client

    return patch(f"{module_path}.httpx.AsyncClient", mock_cls)


# =============================================================================
# Phase 2 Client Tests (exercising actual client)
# =============================================================================

class TestPhase2Client:
    """Test Phase 2 mission client using actual client class."""

    @pytest.mark.asyncio
    async def test_get_mission_success(self):
        """Client fetches and validates a mission."""
        mission_data = make_mission()
        transport = MockTransport({
            "/api/v1/missions/mission_test_001": (200, mission_data),
        })

        with _patch_httpx_client("tars.phase7.phase2_client", transport):
            client = Phase2Client(base_url="http://mock")
            result = await client.get_mission("mission_test_001")

            assert result["mission_id"] == "mission_test_001"
            assert result["drone_id"] == "tars-sim-01"
            assert result["mission_result"] == "success"

    @pytest.mark.asyncio
    async def test_get_mission_not_found(self):
        """Client raises Phase2NotFoundError for 404."""
        transport = MockTransport({
            "/api/v1/missions/nonexistent": (404, {"detail": "Not found"}),
        })

        with _patch_httpx_client("tars.phase7.phase2_client", transport):
            client = Phase2Client(base_url="http://mock")
            with pytest.raises(Phase2NotFoundError):
                await client.get_mission("nonexistent")

    @pytest.mark.asyncio
    async def test_get_mission_server_error(self):
        """Client raises Phase2UnavailableError for 5xx."""
        transport = MockTransport({
            "/api/v1/missions/m1": (500, {"detail": "Internal error"}),
        })

        with _patch_httpx_client("tars.phase7.phase2_client", transport):
            client = Phase2Client(base_url="http://mock")
            with pytest.raises(Phase2UnavailableError):
                await client.get_mission("m1")

    @pytest.mark.asyncio
    async def test_get_mission_connection_error(self):
        """Client raises Phase2UnavailableError on connection failure."""
        transport = ErrorTransport()

        with _patch_httpx_client("tars.phase7.phase2_client", transport):
            client = Phase2Client(base_url="http://mock")
            with pytest.raises(Phase2UnavailableError):
                await client.get_mission("m1")

    @pytest.mark.asyncio
    async def test_get_mission_id_mismatch(self):
        """Client raises ValueError when returned mission_id doesn't match."""
        bad_data = make_mission(mission_id="wrong_id")
        transport = MockTransport({
            "/api/v1/missions/mission_test_001": (200, bad_data),
        })

        with _patch_httpx_client("tars.phase7.phase2_client", transport):
            client = Phase2Client(base_url="http://mock")
            with pytest.raises(ValueError, match="mismatch"):
                await client.get_mission("mission_test_001")

    @pytest.mark.asyncio
    async def test_get_mission_missing_fields(self):
        """Client raises ValueError when required fields are missing."""
        bad_data = {"mission_id": "m1"}  # Missing drone_id, start_time, etc.
        transport = MockTransport({
            "/api/v1/missions/m1": (200, bad_data),
        })

        with _patch_httpx_client("tars.phase7.phase2_client", transport):
            client = Phase2Client(base_url="http://mock")
            with pytest.raises(ValueError, match="missing required fields"):
                await client.get_mission("m1")


# =============================================================================
# Phase 4 Client Tests (exercising actual client)
# =============================================================================

class TestPhase4Client:
    """Test Phase 4 incident client using actual client class."""

    @pytest.mark.asyncio
    async def test_get_incidents_success(self):
        """Client fetches and validates incidents."""
        incidents = [make_incident()]
        response_data = {
            "mission_id": "mission_test_001",
            "incidents": incidents,
            "total": 1,
        }

        transport = MockTransport({
            "/api/v1/incidents/mission_test_001": (200, response_data),
        })

        with _patch_httpx_client("tars.phase7.phase4_client", transport):
            client = Phase4Client(base_url="http://mock")
            result = await client.get_incidents("mission_test_001")

            assert len(result) == 1
            assert result[0]["incident_id"] == "inc_test_001"

    @pytest.mark.asyncio
    async def test_get_incidents_empty(self):
        """Client returns empty list for no incidents."""
        response_data = {
            "mission_id": "mission_test_001",
            "incidents": [],
            "total": 0,
        }

        transport = MockTransport({
            "/api/v1/incidents/mission_test_001": (200, response_data),
        })

        with _patch_httpx_client("tars.phase7.phase4_client", transport):
            client = Phase4Client(base_url="http://mock")
            result = await client.get_incidents("mission_test_001")
            assert result == []

    @pytest.mark.asyncio
    async def test_get_incidents_mission_id_mismatch(self):
        """Client raises ValueError when incident mission_id doesn't match."""
        bad_incident = make_incident(mission_id="wrong_mission")
        response_data = {
            "mission_id": "mission_test_001",
            "incidents": [bad_incident],
            "total": 1,
        }

        transport = MockTransport({
            "/api/v1/incidents/mission_test_001": (200, response_data),
        })

        with _patch_httpx_client("tars.phase7.phase4_client", transport):
            client = Phase4Client(base_url="http://mock")
            with pytest.raises(ValueError, match="mismatch"):
                await client.get_incidents("mission_test_001")

    @pytest.mark.asyncio
    async def test_get_incidents_server_error(self):
        """Client raises Phase4UnavailableError for 5xx."""
        transport = MockTransport({
            "/api/v1/incidents/m1": (500, {"detail": "Internal error"}),
        })

        with _patch_httpx_client("tars.phase7.phase4_client", transport):
            client = Phase4Client(base_url="http://mock")
            with pytest.raises(Phase4UnavailableError):
                await client.get_incidents("m1")


# =============================================================================
# Phase 5 Client Tests (exercising actual client)
# =============================================================================

class TestPhase5Client:
    """Test Phase 5 reasoning client using actual client class."""

    @pytest.mark.asyncio
    async def test_get_analyses_success(self):
        """Client fetches and validates analyses."""
        analyses = [make_reasoning()]
        response_data = {
            "mission_id": "mission_test_001",
            "analyses": analyses,
            "total": 1,
        }

        transport = MockTransport({
            "/api/v1/reasoning/mission_test_001": (200, response_data),
        })

        with _patch_httpx_client("tars.phase7.phase5_client", transport):
            client = Phase5Client(base_url="http://mock")
            result = await client.get_analyses("mission_test_001")

            assert len(result) == 1
            assert result[0]["reasoning_id"] == "reason_test_001"

    @pytest.mark.asyncio
    async def test_get_analyses_404_returns_empty(self):
        """Client returns empty list for 404 (no analyses)."""
        transport = MockTransport({
            "/api/v1/reasoning/mission_test_001": (404, {"detail": "Not found"}),
        })

        with _patch_httpx_client("tars.phase7.phase5_client", transport):
            client = Phase5Client(base_url="http://mock")
            result = await client.get_analyses("mission_test_001")
            assert result == []

    @pytest.mark.asyncio
    async def test_get_analyses_server_error(self):
        """Client raises Phase5UnavailableError for 5xx."""
        transport = MockTransport({
            "/api/v1/reasoning/m1": (500, {"detail": "Internal error"}),
        })

        with _patch_httpx_client("tars.phase7.phase5_client", transport):
            client = Phase5Client(base_url="http://mock")
            with pytest.raises(Phase5UnavailableError):
                await client.get_analyses("m1")

    @pytest.mark.asyncio
    async def test_get_analyses_mission_id_mismatch(self):
        """Client raises ValueError when analysis mission_id doesn't match."""
        bad_analysis = make_reasoning(mission_id="wrong_mission")
        response_data = {
            "mission_id": "mission_test_001",
            "analyses": [bad_analysis],
            "total": 1,
        }

        transport = MockTransport({
            "/api/v1/reasoning/mission_test_001": (200, response_data),
        })

        with _patch_httpx_client("tars.phase7.phase5_client", transport):
            client = Phase5Client(base_url="http://mock")
            with pytest.raises(ValueError, match="mismatch"):
                await client.get_analyses("mission_test_001")


# =============================================================================
# Fake Client Tests (from conftest)
# =============================================================================

class TestFakeClients:
    """Test that fake clients work correctly for service tests."""

    @pytest.mark.asyncio
    async def test_fake_phase2_returns_mission(self, fake_phase2):
        result = await fake_phase2.get_mission("mission_test_001")
        assert result["mission_id"] == "mission_test_001"

    @pytest.mark.asyncio
    async def test_fake_phase2_not_found(self, fake_phase2):
        with pytest.raises(Phase2NotFoundError):
            await fake_phase2.get_mission("nonexistent")

    @pytest.mark.asyncio
    async def test_fake_phase4_returns_incidents(self, fake_phase4):
        result = await fake_phase4.get_incidents("mission_test_001")
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_fake_phase4_empty_for_unknown(self, fake_phase4):
        result = await fake_phase4.get_incidents("nonexistent")
        assert result == []

    @pytest.mark.asyncio
    async def test_fake_phase5_returns_analyses(self, fake_phase5):
        result = await fake_phase5.get_analyses("mission_test_001")
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_fake_phase5_unavailable(self, fake_phase5_unavailable):
        with pytest.raises(Phase5UnavailableError):
            await fake_phase5_unavailable.get_analyses("mission_test_001")

    @pytest.mark.asyncio
    async def test_fake_health_checks(self, fake_phase2, fake_phase4, fake_phase5):
        assert await fake_phase2.health_check() is True
        assert await fake_phase4.health_check() is True
        assert await fake_phase5.health_check() is True
