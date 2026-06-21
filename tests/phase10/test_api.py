"""
Phase 10 API Tests
====================
Tests for health, run creation, candidate lookup, evidence lookup,
and disabled service behavior.

Uses FastAPI TestClient with dependency injection overrides.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from tars.phase10.api import app, _create_service
from tars.phase10.models import (
    CandidateKnowledge,
    CandidateResponse,
    CandidateStatus,
    CandidateType,
    EvidenceListResponse,
    EvidenceResponse,
    HealthResponse,
    LearningRunResponse,
    LearningRunStatus,
)

from .conftest import FakeRepository, make_evidence


# =============================================================================
# Test Health Endpoint
# =============================================================================

class TestHealthEndpoint:
    """Test the /health endpoint."""

    def test_health_returns_ok(self):
        """Health should return status when service is enabled."""
        with patch("tars.phase10.api.settings") as mock_settings:
            mock_settings.LEARNING_ENABLED = True
            mock_settings.LEARNING_VERSION = "phase10.v1-test"
            mock_settings.LEARNING_TRACE_METADATA_ENABLED = False

            with patch(
                "tars.phase10.api.check_database",
                new_callable=AsyncMock,
                return_value=True,
            ):
                with patch("tars.phase10.api._phase9_client", None):
                    client = TestClient(app, raise_server_exceptions=False)
                    resp = client.get("/health")
                    assert resp.status_code == 200
                    data = resp.json()
                    assert data["status"] in ("ok", "degraded")

    def test_health_disabled(self):
        """Health should return disabled when service is off."""
        with patch("tars.phase10.api.settings") as mock_settings:
            mock_settings.LEARNING_ENABLED = False
            mock_settings.LEARNING_VERSION = "phase10.v1-test"

            client = TestClient(app, raise_server_exceptions=False)
            resp = client.get("/health")
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "disabled"


# =============================================================================
# Test Disabled Service
# =============================================================================

class TestDisabledService:
    """Test that disabled service returns 503."""

    def test_run_disabled(self):
        """POST /runs should return 503 when disabled."""
        with patch("tars.phase10.api.settings") as mock_settings:
            mock_settings.LEARNING_ENABLED = False

            client = TestClient(app, raise_server_exceptions=False)
            resp = client.post(
                "/api/v1/learning/runs",
                json={"mission_ids": ["m1"]},
            )
            assert resp.status_code == 503

    def test_list_candidates_disabled(self):
        """GET /candidates should return 503 when disabled."""
        with patch("tars.phase10.api.settings") as mock_settings:
            mock_settings.LEARNING_ENABLED = False

            client = TestClient(app, raise_server_exceptions=False)
            resp = client.get("/api/v1/learning/candidates")
            assert resp.status_code == 503

    def test_get_candidate_disabled(self):
        """GET /candidates/{id} should return 503 when disabled."""
        with patch("tars.phase10.api.settings") as mock_settings:
            mock_settings.LEARNING_ENABLED = False

            client = TestClient(app, raise_server_exceptions=False)
            resp = client.get("/api/v1/learning/candidates/cand_001")
            assert resp.status_code == 503

    def test_evidence_disabled(self):
        """GET /candidates/{id}/evidence should return 503 when disabled."""
        with patch("tars.phase10.api.settings") as mock_settings:
            mock_settings.LEARNING_ENABLED = False

            client = TestClient(app, raise_server_exceptions=False)
            resp = client.get(
                "/api/v1/learning/candidates/cand_001/evidence"
            )
            assert resp.status_code == 503

    def test_retire_disabled(self):
        """POST /candidates/{id}/retire should return 503 when disabled."""
        with patch("tars.phase10.api.settings") as mock_settings:
            mock_settings.LEARNING_ENABLED = False

            client = TestClient(app, raise_server_exceptions=False)
            resp = client.post(
                "/api/v1/learning/candidates/cand_001/retire",
                json={"reason": "test"},
            )
            assert resp.status_code == 503


# =============================================================================
# Test Response Models
# =============================================================================

class TestResponseModels:
    """Test that response models carry required fields."""

    def test_candidate_response_advisory_only(self):
        """CandidateResponse must always have advisory_only=True."""
        resp = CandidateResponse(
            candidate_id="cand_001",
            candidate_type=CandidateType.MITIGATION_EFFECTIVENESS,
            status=CandidateStatus.PROPOSED,
            statement="Test.",
        )
        assert resp.advisory_only is True

    def test_learning_run_response_fields(self):
        """LearningRunResponse should have all required fields."""
        resp = LearningRunResponse(
            run_id="run_001",
            status=LearningRunStatus.COMPLETE,
            learning_version="phase10.v1",
        )
        assert resp.run_id == "run_001"
        assert resp.status == LearningRunStatus.COMPLETE
        assert resp.candidates_proposed == 0
        assert resp.warnings == []

    def test_health_response_fields(self):
        """HealthResponse should have all required fields."""
        resp = HealthResponse(
            status="ok",
            postgres="ok",
            phase9="ok",
            learning_version="phase10.v1",
        )
        assert resp.status == "ok"
        assert resp.learning_version == "phase10.v1"

    def test_evidence_response_fields(self):
        """EvidenceResponse should carry all evidence fields."""
        resp = EvidenceResponse(
            evidence_id="ev_001",
            candidate_id="cand_001",
            mission_id="mission_001",
            root_cause="gps_interference",
            mitigation="switch_to_visual_odometry",
            outcome="recovered",
            overall_score=0.85,
        )
        assert resp.evidence_id == "ev_001"
        assert resp.overall_score == 0.85
