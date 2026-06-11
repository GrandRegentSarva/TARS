"""
Tests for Phase 5 Incident Client
===================================
Tests Phase 4 incident fetching, validation, and error handling.

Uses httpx mock responses to avoid needing Phase 4 API running.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from tars.phase5.incident_client import IncidentClient

from .conftest import make_incident


# =============================================================================
# Fetch and Validate Tests
# =============================================================================

class TestGetIncident:
    """Test incident fetching from Phase 4."""

    @pytest.mark.asyncio
    async def test_fetch_valid_incident(self):
        """Successfully fetch and validate a Phase 4 incident."""
        incident = make_incident()
        mock_request = httpx.Request("GET", "http://test:8003/api/v1/incidents/test_mission/inc_test123")
        mock_response = httpx.Response(
            status_code=200,
            json=incident,
            request=mock_request,
        )

        with patch("httpx.AsyncClient.get", return_value=mock_response):
            client = IncidentClient(base_url="http://test:8003")
            result = await client.get_incident("test_mission", "inc_test123")

        assert result["incident_id"] == "inc_test123"
        assert result["mission_id"] == "test_mission"
        assert result["incident_type"] == "navigation_instability"

    @pytest.mark.asyncio
    async def test_mission_id_mismatch_raises(self):
        """Reject response with mismatched mission_id."""
        incident = make_incident(mission_id="wrong_mission")
        mock_request = httpx.Request("GET", "http://test:8003/api/v1/incidents/test_mission/inc_test123")
        mock_response = httpx.Response(
            status_code=200,
            json=incident,
            request=mock_request,
        )

        with patch("httpx.AsyncClient.get", return_value=mock_response):
            client = IncidentClient(base_url="http://test:8003")
            with pytest.raises(ValueError, match="Mission ID mismatch"):
                await client.get_incident("test_mission", "inc_test123")

    @pytest.mark.asyncio
    async def test_incident_id_mismatch_raises(self):
        """Reject response with mismatched incident_id."""
        incident = make_incident(incident_id="wrong_incident")
        mock_request = httpx.Request("GET", "http://test:8003/api/v1/incidents/test_mission/inc_test123")
        mock_response = httpx.Response(
            status_code=200,
            json=incident,
            request=mock_request,
        )

        with patch("httpx.AsyncClient.get", return_value=mock_response):
            client = IncidentClient(base_url="http://test:8003")
            with pytest.raises(ValueError, match="Incident ID mismatch"):
                await client.get_incident("test_mission", "inc_test123")

    @pytest.mark.asyncio
    async def test_404_raises_http_status_error(self):
        """Phase 4 404 should propagate as HTTPStatusError."""
        mock_response = httpx.Response(
            status_code=404,
            json={"detail": "Not found"},
            request=httpx.Request("GET", "http://test:8003/api/v1/incidents/m/i"),
        )

        with patch("httpx.AsyncClient.get", return_value=mock_response):
            client = IncidentClient(base_url="http://test:8003")
            with pytest.raises(httpx.HTTPStatusError):
                await client.get_incident("test_mission", "inc_nonexistent")

    @pytest.mark.asyncio
    async def test_500_raises_http_status_error(self):
        """Phase 4 5xx should propagate as HTTPStatusError."""
        mock_response = httpx.Response(
            status_code=500,
            json={"detail": "Internal error"},
            request=httpx.Request("GET", "http://test:8003/api/v1/incidents/m/i"),
        )

        with patch("httpx.AsyncClient.get", return_value=mock_response):
            client = IncidentClient(base_url="http://test:8003")
            with pytest.raises(httpx.HTTPStatusError):
                await client.get_incident("test_mission", "inc_test123")

    @pytest.mark.asyncio
    async def test_connect_error_propagates(self):
        """Connection failure should propagate."""
        with patch(
            "httpx.AsyncClient.get",
            side_effect=httpx.ConnectError("Connection refused"),
        ):
            client = IncidentClient(base_url="http://unreachable:8003")
            with pytest.raises(httpx.ConnectError):
                await client.get_incident("test_mission", "inc_test123")


# =============================================================================
# Incident Field Validation Tests
# =============================================================================

class TestIncidentFieldValidation:
    """Test that Phase 4 responses are validated against the Incident contract."""

    @pytest.mark.asyncio
    async def test_missing_incident_type_rejected(self):
        """Response missing incident_type should be rejected."""
        incident = make_incident()
        del incident["incident_type"]
        mock_request = httpx.Request("GET", "http://test:8003/api/v1/incidents/test_mission/inc_test123")
        mock_response = httpx.Response(
            status_code=200,
            json=incident,
            request=mock_request,
        )

        with patch("httpx.AsyncClient.get", return_value=mock_response):
            client = IncidentClient(base_url="http://test:8003")
            with pytest.raises(ValueError, match="missing required fields"):
                await client.get_incident("test_mission", "inc_test123")

    @pytest.mark.asyncio
    async def test_missing_severity_rejected(self):
        """Response missing severity should be rejected."""
        incident = make_incident()
        del incident["severity"]
        mock_request = httpx.Request("GET", "http://test:8003/api/v1/incidents/test_mission/inc_test123")
        mock_response = httpx.Response(
            status_code=200,
            json=incident,
            request=mock_request,
        )

        with patch("httpx.AsyncClient.get", return_value=mock_response):
            client = IncidentClient(base_url="http://test:8003")
            with pytest.raises(ValueError, match="missing required fields"):
                await client.get_incident("test_mission", "inc_test123")

    @pytest.mark.asyncio
    async def test_missing_evidence_rejected(self):
        """Response missing evidence should be rejected."""
        incident = make_incident()
        del incident["evidence"]
        mock_request = httpx.Request("GET", "http://test:8003/api/v1/incidents/test_mission/inc_test123")
        mock_response = httpx.Response(
            status_code=200,
            json=incident,
            request=mock_request,
        )

        with patch("httpx.AsyncClient.get", return_value=mock_response):
            client = IncidentClient(base_url="http://test:8003")
            with pytest.raises(ValueError, match="missing required fields"):
                await client.get_incident("test_mission", "inc_test123")

    @pytest.mark.asyncio
    async def test_missing_multiple_fields_rejected(self):
        """Response missing multiple fields should list them all."""
        incident = make_incident()
        del incident["incident_type"]
        del incident["severity"]
        del incident["evidence"]
        mock_request = httpx.Request("GET", "http://test:8003/api/v1/incidents/test_mission/inc_test123")
        mock_response = httpx.Response(
            status_code=200,
            json=incident,
            request=mock_request,
        )

        with patch("httpx.AsyncClient.get", return_value=mock_response):
            client = IncidentClient(base_url="http://test:8003")
            with pytest.raises(ValueError, match="missing required fields"):
                await client.get_incident("test_mission", "inc_test123")

    @pytest.mark.asyncio
    async def test_empty_incident_type_rejected(self):
        """Empty incident_type string should be rejected."""
        incident = make_incident()
        incident["incident_type"] = ""
        mock_request = httpx.Request("GET", "http://test:8003/api/v1/incidents/test_mission/inc_test123")
        mock_response = httpx.Response(
            status_code=200,
            json=incident,
            request=mock_request,
        )

        with patch("httpx.AsyncClient.get", return_value=mock_response):
            client = IncidentClient(base_url="http://test:8003")
            with pytest.raises(ValueError, match="invalid 'incident_type'"):
                await client.get_incident("test_mission", "inc_test123")

    @pytest.mark.asyncio
    async def test_evidence_not_list_rejected(self):
        """evidence as a string instead of list should be rejected."""
        incident = make_incident()
        incident["evidence"] = "not a list"
        mock_request = httpx.Request("GET", "http://test:8003/api/v1/incidents/test_mission/inc_test123")
        mock_response = httpx.Response(
            status_code=200,
            json=incident,
            request=mock_request,
        )

        with patch("httpx.AsyncClient.get", return_value=mock_response):
            client = IncidentClient(base_url="http://test:8003")
            with pytest.raises(ValueError, match="'evidence' must be a list"):
                await client.get_incident("test_mission", "inc_test123")

    @pytest.mark.asyncio
    async def test_phases_not_list_rejected(self):
        """phases as a string instead of list should be rejected."""
        incident = make_incident()
        incident["phases"] = "cruise"
        mock_request = httpx.Request("GET", "http://test:8003/api/v1/incidents/test_mission/inc_test123")
        mock_response = httpx.Response(
            status_code=200,
            json=incident,
            request=mock_request,
        )

        with patch("httpx.AsyncClient.get", return_value=mock_response):
            client = IncidentClient(base_url="http://test:8003")
            with pytest.raises(ValueError, match="'phases' must be a list"):
                await client.get_incident("test_mission", "inc_test123")


# =============================================================================
# Health Check Tests
# =============================================================================

class TestHealthCheck:
    """Test Phase 4 health check."""

    @pytest.mark.asyncio
    async def test_health_ok(self):
        mock_response = httpx.Response(status_code=200, json={"status": "ok"})
        with patch("httpx.AsyncClient.get", return_value=mock_response):
            client = IncidentClient(base_url="http://test:8003")
            assert await client.health_check() is True

    @pytest.mark.asyncio
    async def test_health_unreachable(self):
        with patch(
            "httpx.AsyncClient.get",
            side_effect=httpx.ConnectError("Connection refused"),
        ):
            client = IncidentClient(base_url="http://unreachable:8003")
            assert await client.health_check() is False

    @pytest.mark.asyncio
    async def test_health_non_200(self):
        mock_response = httpx.Response(status_code=503, json={})
        with patch("httpx.AsyncClient.get", return_value=mock_response):
            client = IncidentClient(base_url="http://test:8003")
            assert await client.health_check() is False
