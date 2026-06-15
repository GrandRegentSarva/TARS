"""
Phase 7 Model Tests
====================
Tests for Pydantic models, enums, and validation.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from tars.phase7.models import (
    ApplyMitigationRequest,
    OutcomeScope,
    OutcomeStatus,
    RecordOutcomeRequest,
    SyncCounts,
    SyncRequest,
    SyncStatus,
    MitigationSource,
    OutcomeSource,
    MissionRecord,
    IncidentRecord,
    RootCauseRecord,
    MitigationRecord,
    AnalysisRelationship,
    RecommendationRelationship,
    OutcomeRecord,
    MissionProjection,
)


# =============================================================================
# Enum Tests
# =============================================================================

class TestOutcomeStatus:
    """Test controlled outcome statuses."""

    def test_all_statuses_defined(self):
        expected = {"recovered", "stabilized", "degraded", "failed", "unknown"}
        actual = {s.value for s in OutcomeStatus}
        assert actual == expected

    def test_status_from_string(self):
        assert OutcomeStatus("recovered") == OutcomeStatus.RECOVERED
        assert OutcomeStatus("failed") == OutcomeStatus.FAILED

    def test_invalid_status_raises(self):
        with pytest.raises(ValueError):
            OutcomeStatus("invalid_status")


class TestSyncStatus:
    """Test sync status enum."""

    def test_all_statuses_defined(self):
        expected = {"processing", "complete", "failed"}
        actual = {s.value for s in SyncStatus}
        assert actual == expected


class TestOutcomeScope:
    """Test outcome scope enum."""

    def test_scopes(self):
        assert OutcomeScope.MISSION.value == "mission"
        assert OutcomeScope.INCIDENT.value == "incident"


# =============================================================================
# Sync Request/Response Tests
# =============================================================================

class TestSyncRequest:
    """Test sync request model."""

    def test_defaults(self):
        req = SyncRequest()
        assert req.include_reasoning is True
        assert req.require_reasoning is False

    def test_custom_values(self):
        req = SyncRequest(include_reasoning=False, require_reasoning=True)
        assert req.include_reasoning is False
        assert req.require_reasoning is True


class TestSyncCounts:
    """Test sync counts model."""

    def test_defaults(self):
        counts = SyncCounts()
        assert counts.missions == 0
        assert counts.incidents == 0
        assert counts.root_causes == 0
        assert counts.mitigations == 0
        assert counts.outcomes == 0
        assert counts.relationships == 0
        assert counts.analyses_skipped == 0


# =============================================================================
# Observation Request Tests
# =============================================================================

class TestApplyMitigationRequest:
    """Test applied mitigation request validation."""

    def test_valid_request(self):
        req = ApplyMitigationRequest(
            idempotency_key="apply_001",
            description="Switched to visual odometry",
            applied_at=datetime.now(timezone.utc),
            recorded_by="operator",
        )
        assert req.idempotency_key == "apply_001"
        assert req.notes is None

    def test_empty_idempotency_key_rejected(self):
        with pytest.raises(ValidationError):
            ApplyMitigationRequest(
                idempotency_key="",
                description="Test",
                applied_at=datetime.now(timezone.utc),
                recorded_by="operator",
            )

    def test_empty_description_rejected(self):
        with pytest.raises(ValidationError):
            ApplyMitigationRequest(
                idempotency_key="apply_001",
                description="",
                applied_at=datetime.now(timezone.utc),
                recorded_by="operator",
            )

    def test_notes_truncated(self):
        long_notes = "x" * 3000
        req = ApplyMitigationRequest(
            idempotency_key="apply_001",
            description="Test mitigation",
            applied_at=datetime.now(timezone.utc),
            recorded_by="operator",
            notes=long_notes,
        )
        assert len(req.notes) == 2000


class TestRecordOutcomeRequest:
    """Test outcome observation request validation."""

    def test_valid_request(self):
        req = RecordOutcomeRequest(
            idempotency_key="outcome_001",
            status=OutcomeStatus.RECOVERED,
            description="Navigation stabilized within 12 seconds",
            observed_at=datetime.now(timezone.utc),
            recorded_by="operator",
        )
        assert req.status == OutcomeStatus.RECOVERED
        assert req.mitigation_application_id is None

    def test_with_mitigation_reference(self):
        req = RecordOutcomeRequest(
            idempotency_key="outcome_001",
            status=OutcomeStatus.RECOVERED,
            description="Stabilized after switching nav source",
            observed_at=datetime.now(timezone.utc),
            recorded_by="operator",
            mitigation_application_id="apply_001",
        )
        assert req.mitigation_application_id == "apply_001"

    def test_invalid_status_rejected(self):
        with pytest.raises(ValidationError):
            RecordOutcomeRequest(
                idempotency_key="outcome_001",
                status="invalid",
                description="Test",
                observed_at=datetime.now(timezone.utc),
                recorded_by="operator",
            )

    def test_description_truncated(self):
        long_desc = "y" * 3000
        req = RecordOutcomeRequest(
            idempotency_key="outcome_001",
            status=OutcomeStatus.RECOVERED,
            description=long_desc,
            observed_at=datetime.now(timezone.utc),
            recorded_by="operator",
        )
        assert len(req.description) == 2000


# =============================================================================
# Internal Record Tests
# =============================================================================

class TestMissionRecord:
    """Test mission record model."""

    def test_valid_record(self):
        rec = MissionRecord(
            mission_id="m1",
            drone_id="d1",
            start_time=datetime.now(timezone.utc),
            mission_result="success",
        )
        assert rec.source_phase == "phase2"
        assert rec.end_time is None


class TestIncidentRecord:
    """Test incident record model."""

    def test_valid_record(self):
        rec = IncidentRecord(
            incident_id="i1",
            mission_id="m1",
            incident_type="navigation_instability",
            severity="high",
            start_ms=1000,
            end_ms=5000,
            peak_risk=0.8,
        )
        assert rec.source_phase == "phase4"
        assert rec.phases == []
        assert rec.evidence == []

    def test_peak_risk_bounds(self):
        with pytest.raises(ValidationError):
            IncidentRecord(
                incident_id="i1",
                mission_id="m1",
                incident_type="test",
                severity="high",
                start_ms=0,
                end_ms=1000,
                peak_risk=1.5,
            )


class TestRootCauseRecord:
    """Test root cause record model."""

    def test_valid_record(self):
        rec = RootCauseRecord(
            root_cause_id="rc_abc",
            classification="GPS interference",
            normalized_classification="gps interference",
        )
        assert rec.source_phase == "phase5"


class TestMitigationRecord:
    """Test mitigation record model."""

    def test_defaults(self):
        rec = MitigationRecord(
            mitigation_id="mit_abc",
            description="Switch to visual odometry",
            normalized_description="switch to visual odometry",
        )
        assert rec.advisory_only is True
        assert rec.source == "phase5_recommendation"


class TestMissionProjection:
    """Test mission projection model."""

    def test_empty_projection(self):
        proj = MissionProjection(
            mission=MissionRecord(
                mission_id="m1",
                drone_id="d1",
                start_time=datetime.now(timezone.utc),
                mission_result="success",
            ),
        )
        assert proj.incidents == []
        assert proj.root_causes == []
        assert proj.mitigations == []
        assert proj.analyses == []
        assert proj.recommendations == []
        assert proj.outcomes == []
        assert proj.mission_outcome is None
