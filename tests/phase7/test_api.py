"""
Phase 7 API Tests
==================
Tests for the FastAPI Operational Memory API endpoints.

Uses httpx AsyncClient with the FastAPI test client.
Mocks Neo4j connectivity and service layer to avoid requiring
live Neo4j or upstream services.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from tars.phase7.api import app
from tars.phase7.models import (
    ApplyMitigationResponse,
    IncidentMemoryResponse,
    OutcomeScope,
    OutcomeStatus,
    RecordOutcomeResponse,
    SimilarHistoryResponse,
    SyncCounts,
    SyncResponse,
    SyncStatus,
    SyncStatusResponse,
)


# =============================================================================
# Test Client Helper
# =============================================================================

@pytest.fixture
def api_client():
    """Create an async test client for the Phase 7 API."""
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


# =============================================================================
# Health Tests
# =============================================================================

class TestHealthEndpoint:
    """Test GET /health endpoint."""

    @pytest.mark.asyncio
    async def test_health_returns_status(self, api_client):
        """Health endpoint returns a response."""
        with patch("tars.phase7.api.check_connectivity", new_callable=AsyncMock, return_value=False):
            with patch("tars.phase7.api._service", None):
                async with api_client as client:
                    response = await client.get("/health")
                    assert response.status_code == 200
                    data = response.json()
                    assert "status" in data
                    assert "neo4j" in data


# =============================================================================
# Sync Endpoint Tests
# =============================================================================

class TestSyncEndpoint:
    """Test POST /api/v1/memory/sync/{mission_id} endpoint."""

    @pytest.mark.asyncio
    async def test_sync_neo4j_unavailable(self, api_client):
        """Sync returns 503 when Neo4j is unavailable."""
        with patch("tars.phase7.api.check_connectivity", new_callable=AsyncMock, return_value=False):
            async with api_client as client:
                response = await client.post(
                    "/api/v1/memory/sync/m1",
                    json={"include_reasoning": True, "require_reasoning": False},
                )
                assert response.status_code == 503

    @pytest.mark.asyncio
    async def test_sync_success(self, api_client):
        """Sync returns success response."""
        now = datetime.now(timezone.utc)
        mock_service = MagicMock()
        mock_service.sync_mission = AsyncMock(return_value=SyncResponse(
            mission_id="m1",
            status=SyncStatus.COMPLETE,
            counts=SyncCounts(missions=1, incidents=1),
            started_at=now,
            completed_at=now,
        ))

        with patch("tars.phase7.api.check_connectivity", new_callable=AsyncMock, return_value=True):
            with patch("tars.phase7.api._service", mock_service):
                async with api_client as client:
                    response = await client.post(
                        "/api/v1/memory/sync/m1",
                        json={"include_reasoning": True, "require_reasoning": False},
                    )
                    assert response.status_code == 200
                    data = response.json()
                    assert data["mission_id"] == "m1"
                    assert data["status"] == "complete"

    @pytest.mark.asyncio
    async def test_sync_mission_not_found(self, api_client):
        """Sync returns 404 when mission not found."""
        now = datetime.now(timezone.utc)
        mock_service = MagicMock()
        mock_service.sync_mission = AsyncMock(return_value=SyncResponse(
            mission_id="nonexistent",
            status=SyncStatus.FAILED,
            started_at=now,
            completed_at=now,
            error_code="mission_not_found",
            error_message="Mission 'nonexistent' not found in Phase 2",
        ))

        with patch("tars.phase7.api.check_connectivity", new_callable=AsyncMock, return_value=True):
            with patch("tars.phase7.api._service", mock_service):
                async with api_client as client:
                    response = await client.post(
                        "/api/v1/memory/sync/nonexistent",
                        json={},
                    )
                    assert response.status_code == 404


# =============================================================================
# Sync Status Tests
# =============================================================================

class TestSyncStatusEndpoint:
    """Test GET /api/v1/memory/sync/{mission_id} endpoint."""

    @pytest.mark.asyncio
    async def test_sync_status_found(self, api_client):
        """Sync status returns data when available."""
        now = datetime.now(timezone.utc)
        mock_service = MagicMock()
        mock_service.get_sync_status = AsyncMock(return_value=SyncStatusResponse(
            mission_id="m1",
            status=SyncStatus.COMPLETE,
            started_at=now,
            completed_at=now,
            counts=SyncCounts(missions=1),
        ))

        with patch("tars.phase7.api.check_connectivity", new_callable=AsyncMock, return_value=True):
            with patch("tars.phase7.api._service", mock_service):
                async with api_client as client:
                    response = await client.get("/api/v1/memory/sync/m1")
                    assert response.status_code == 200
                    data = response.json()
                    assert data["mission_id"] == "m1"

    @pytest.mark.asyncio
    async def test_sync_status_not_found(self, api_client):
        """Sync status returns 404 when no record exists."""
        mock_service = MagicMock()
        mock_service.get_sync_status = AsyncMock(return_value=None)

        with patch("tars.phase7.api.check_connectivity", new_callable=AsyncMock, return_value=True):
            with patch("tars.phase7.api._service", mock_service):
                async with api_client as client:
                    response = await client.get("/api/v1/memory/sync/nonexistent")
                    assert response.status_code == 404


# =============================================================================
# Incident Memory Tests
# =============================================================================

class TestIncidentMemoryEndpoint:
    """Test GET /api/v1/memory/incidents/{incident_id} endpoint."""

    @pytest.mark.asyncio
    async def test_incident_memory_found(self, api_client):
        """Incident memory returns full neighborhood."""
        mock_service = MagicMock()
        mock_service.get_incident_memory = AsyncMock(return_value=IncidentMemoryResponse(
            incident_id="inc_001",
            mission_id="m1",
            incident_type="navigation_instability",
            severity="high",
            start_ms=5000,
            end_ms=10000,
            peak_risk=0.78,
            phases=["cruise"],
            evidence=["GPS degraded"],
        ))

        with patch("tars.phase7.api.check_connectivity", new_callable=AsyncMock, return_value=True):
            with patch("tars.phase7.api._service", mock_service):
                async with api_client as client:
                    response = await client.get("/api/v1/memory/incidents/inc_001")
                    assert response.status_code == 200
                    data = response.json()
                    assert data["incident_id"] == "inc_001"
                    assert "root_causes" in data
                    assert "recommended_mitigations" in data
                    assert "applied_mitigations" in data
                    assert "outcomes" in data

    @pytest.mark.asyncio
    async def test_incident_memory_not_found(self, api_client):
        """Incident memory returns 404 for unknown incident."""
        mock_service = MagicMock()
        mock_service.get_incident_memory = AsyncMock(return_value=None)

        with patch("tars.phase7.api.check_connectivity", new_callable=AsyncMock, return_value=True):
            with patch("tars.phase7.api._service", mock_service):
                async with api_client as client:
                    response = await client.get("/api/v1/memory/incidents/nonexistent")
                    assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_incident_memory_neo4j_unavailable(self, api_client):
        """Incident memory returns 503 when Neo4j is unavailable."""
        with patch("tars.phase7.api.check_connectivity", new_callable=AsyncMock, return_value=False):
            async with api_client as client:
                response = await client.get("/api/v1/memory/incidents/inc_001")
                assert response.status_code == 503


# =============================================================================
# Similar History Tests
# =============================================================================

class TestSimilarHistoryEndpoint:
    """Test GET /api/v1/memory/incidents/{incident_id}/similar endpoint."""

    @pytest.mark.asyncio
    async def test_similar_history_found(self, api_client):
        """Similar history returns matches."""
        mock_service = MagicMock()
        mock_service.find_similar_incidents = AsyncMock(
            return_value=SimilarHistoryResponse(
                query_incident_id="inc_001",
                matches=[],
                total=0,
            )
        )

        with patch("tars.phase7.api.check_connectivity", new_callable=AsyncMock, return_value=True):
            with patch("tars.phase7.api._service", mock_service):
                async with api_client as client:
                    response = await client.get(
                        "/api/v1/memory/incidents/inc_001/similar?limit=10"
                    )
                    assert response.status_code == 200
                    data = response.json()
                    assert data["query_incident_id"] == "inc_001"
                    assert "matches" in data
                    assert "total" in data


# =============================================================================
# Mitigation Endpoint Tests
# =============================================================================

class TestMitigationEndpoint:
    """Test POST /api/v1/memory/incidents/{incident_id}/mitigations endpoint."""

    @pytest.mark.asyncio
    async def test_apply_mitigation_success(self, api_client):
        """Apply mitigation returns success."""
        now = datetime.now(timezone.utc)
        mock_service = MagicMock()
        mock_service.apply_mitigation = AsyncMock(
            return_value=ApplyMitigationResponse(
                application_id="apply_001",
                incident_id="inc_001",
                mitigation_id="mit_abc",
                description="Switched to visual odometry",
                applied_at=now,
                recorded_by="operator",
                created=True,
            )
        )

        with patch("tars.phase7.api.check_connectivity", new_callable=AsyncMock, return_value=True):
            with patch("tars.phase7.api._service", mock_service):
                async with api_client as client:
                    response = await client.post(
                        "/api/v1/memory/incidents/inc_001/mitigations",
                        json={
                            "idempotency_key": "apply_001",
                            "description": "Switched to visual odometry",
                            "applied_at": now.isoformat(),
                            "recorded_by": "operator",
                        },
                    )
                    assert response.status_code == 200
                    data = response.json()
                    assert data["application_id"] == "apply_001"
                    assert data["created"] is True

    @pytest.mark.asyncio
    async def test_apply_mitigation_incident_not_found(self, api_client):
        """Apply mitigation returns 404 for unknown incident."""
        now = datetime.now(timezone.utc)
        mock_service = MagicMock()
        mock_service.apply_mitigation = AsyncMock(
            side_effect=ValueError("Incident 'inc_999' not found in graph")
        )

        with patch("tars.phase7.api.check_connectivity", new_callable=AsyncMock, return_value=True):
            with patch("tars.phase7.api._service", mock_service):
                async with api_client as client:
                    response = await client.post(
                        "/api/v1/memory/incidents/inc_999/mitigations",
                        json={
                            "idempotency_key": "apply_001",
                            "description": "Test",
                            "applied_at": now.isoformat(),
                            "recorded_by": "operator",
                        },
                    )
                    assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_apply_mitigation_validation_error(self, api_client):
        """Apply mitigation returns 422 for invalid request."""
        with patch("tars.phase7.api.check_connectivity", new_callable=AsyncMock, return_value=True):
            with patch("tars.phase7.api._service", MagicMock()):
                async with api_client as client:
                    response = await client.post(
                        "/api/v1/memory/incidents/inc_001/mitigations",
                        json={
                            "idempotency_key": "",  # Invalid: empty
                            "description": "Test",
                            "applied_at": "2026-06-15T10:00:00Z",
                            "recorded_by": "operator",
                        },
                    )
                    assert response.status_code == 422


# =============================================================================
# Outcome Endpoint Tests
# =============================================================================

class TestOutcomeEndpoint:
    """Test POST /api/v1/memory/incidents/{incident_id}/outcomes endpoint."""

    @pytest.mark.asyncio
    async def test_record_outcome_success(self, api_client):
        """Record outcome returns success."""
        now = datetime.now(timezone.utc)
        mock_service = MagicMock()
        mock_service.record_outcome = AsyncMock(
            return_value=RecordOutcomeResponse(
                outcome_id="outcome_001",
                incident_id="inc_001",
                scope=OutcomeScope.INCIDENT,
                status=OutcomeStatus.RECOVERED,
                description="Navigation stabilized",
                observed_at=now,
                recorded_by="operator",
                created=True,
            )
        )

        with patch("tars.phase7.api.check_connectivity", new_callable=AsyncMock, return_value=True):
            with patch("tars.phase7.api._service", mock_service):
                async with api_client as client:
                    response = await client.post(
                        "/api/v1/memory/incidents/inc_001/outcomes",
                        json={
                            "idempotency_key": "outcome_001",
                            "status": "recovered",
                            "description": "Navigation stabilized",
                            "observed_at": now.isoformat(),
                            "recorded_by": "operator",
                        },
                    )
                    assert response.status_code == 200
                    data = response.json()
                    assert data["outcome_id"] == "outcome_001"
                    assert data["status"] == "recovered"

    @pytest.mark.asyncio
    async def test_record_outcome_invalid_status(self, api_client):
        """Record outcome returns 422 for invalid status."""
        now = datetime.now(timezone.utc)
        with patch("tars.phase7.api.check_connectivity", new_callable=AsyncMock, return_value=True):
            with patch("tars.phase7.api._service", MagicMock()):
                async with api_client as client:
                    response = await client.post(
                        "/api/v1/memory/incidents/inc_001/outcomes",
                        json={
                            "idempotency_key": "outcome_001",
                            "status": "invalid_status",
                            "description": "Test",
                            "observed_at": now.isoformat(),
                            "recorded_by": "operator",
                        },
                    )
                    assert response.status_code == 422


# =============================================================================
# Security Tests
# =============================================================================

class TestSecurityConstraints:
    """Test that the API does not expose dangerous operations."""

    @pytest.mark.asyncio
    async def test_no_arbitrary_cypher_endpoint(self, api_client):
        """Verify no endpoint accepts raw Cypher queries."""
        async with api_client as client:
            # Try common paths that might expose Cypher
            for path in ["/api/v1/memory/query", "/api/v1/memory/cypher",
                         "/api/v1/cypher", "/cypher"]:
                response = await client.post(
                    path,
                    json={"query": "MATCH (n) RETURN n"},
                )
                # Should be 404 (not found) or 405 (method not allowed)
                assert response.status_code in (404, 405, 422), \
                    f"Unexpected status {response.status_code} for {path}"

    @pytest.mark.asyncio
    async def test_recommended_vs_applied_separate(self, api_client):
        """Verify API response separates recommended and applied mitigations."""
        mock_service = MagicMock()
        mock_service.get_incident_memory = AsyncMock(return_value=IncidentMemoryResponse(
            incident_id="inc_001",
            mission_id="m1",
            incident_type="navigation_instability",
            severity="high",
            start_ms=5000,
            end_ms=10000,
            peak_risk=0.78,
        ))

        with patch("tars.phase7.api.check_connectivity", new_callable=AsyncMock, return_value=True):
            with patch("tars.phase7.api._service", mock_service):
                async with api_client as client:
                    response = await client.get("/api/v1/memory/incidents/inc_001")
                    data = response.json()
                    # Must have separate fields
                    assert "recommended_mitigations" in data
                    assert "applied_mitigations" in data
                    # Must not have a combined field
                    assert "mitigations" not in data
