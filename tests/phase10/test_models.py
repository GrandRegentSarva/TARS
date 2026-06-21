"""
Phase 10 Model Tests
======================
Tests for schema validation, enum constraints, advisory-only behavior,
and secret redaction.
"""

from __future__ import annotations

import pytest

from tars.phase10.models import (
    CandidateKnowledge,
    CandidateStatus,
    CandidateType,
    EvidenceLevel,
    LearningEvidence,
    LearningRunRequest,
    LearningRunResponse,
    LearningRunStatus,
    RetireRequest,
    RunCandidateAction,
)


class TestEnums:
    """Test enum values and constraints."""

    def test_candidate_types(self):
        assert CandidateType.MITIGATION_EFFECTIVENESS == "mitigation_effectiveness"
        assert CandidateType.ROOT_CAUSE_PATTERN == "root_cause_pattern"
        assert CandidateType.REASONING_QUALITY_PATTERN == "reasoning_quality_pattern"
        assert CandidateType.FALSE_POSITIVE_PATTERN == "false_positive_pattern"
        assert CandidateType.FALSE_NEGATIVE_PATTERN == "false_negative_pattern"
        assert CandidateType.RISK_CONTEXT_PATTERN == "risk_context_pattern"

    def test_candidate_statuses(self):
        assert CandidateStatus.PROPOSED == "proposed"
        assert CandidateStatus.SUPERSEDED == "superseded"
        assert CandidateStatus.RETIRED == "retired"
        assert CandidateStatus.REJECTED == "rejected"

    def test_no_validated_status(self):
        """Phase 10 must not create a 'validated' status."""
        values = [s.value for s in CandidateStatus]
        assert "validated" not in values

    def test_evidence_levels(self):
        assert EvidenceLevel.OPERATOR_LABEL == "operator_label"
        assert EvidenceLevel.MISSION_OUTCOME == "mission_outcome"
        assert EvidenceLevel.TRACE_METADATA == "trace_metadata"

    def test_run_statuses(self):
        assert LearningRunStatus.PENDING == "pending"
        assert LearningRunStatus.RUNNING == "running"
        assert LearningRunStatus.COMPLETE == "complete"
        assert LearningRunStatus.FAILED == "failed"

    def test_run_candidate_actions(self):
        assert RunCandidateAction.PROPOSED == "proposed"
        assert RunCandidateAction.UPDATED == "updated"
        assert RunCandidateAction.SUPPRESSED == "suppressed"
        assert RunCandidateAction.UNCHANGED == "unchanged"


class TestCandidateKnowledge:
    """Test CandidateKnowledge model validation."""

    def test_valid_candidate(self):
        c = CandidateKnowledge(
            candidate_id="cand_test_001",
            candidate_type=CandidateType.MITIGATION_EFFECTIVENESS,
            statement="Test statement.",
            confidence=0.75,
            success_rate=0.80,
            learning_version="phase10.v1",
            dedupe_key="test:key",
        )
        assert c.advisory_only is True
        assert c.confidence == 0.75

    def test_advisory_only_must_be_true(self):
        with pytest.raises(ValueError, match="advisory_only must always be True"):
            CandidateKnowledge(
                candidate_id="cand_test_001",
                candidate_type=CandidateType.MITIGATION_EFFECTIVENESS,
                statement="Test statement.",
                advisory_only=False,
            )

    def test_confidence_out_of_bounds_high(self):
        with pytest.raises(ValueError, match="out of bounds"):
            CandidateKnowledge(
                candidate_id="cand_test_001",
                candidate_type=CandidateType.MITIGATION_EFFECTIVENESS,
                statement="Test statement.",
                confidence=1.5,
            )

    def test_confidence_out_of_bounds_low(self):
        with pytest.raises(ValueError, match="out of bounds"):
            CandidateKnowledge(
                candidate_id="cand_test_001",
                candidate_type=CandidateType.MITIGATION_EFFECTIVENESS,
                statement="Test statement.",
                confidence=-0.1,
            )

    def test_success_rate_out_of_bounds(self):
        with pytest.raises(ValueError, match="out of bounds"):
            CandidateKnowledge(
                candidate_id="cand_test_001",
                candidate_type=CandidateType.MITIGATION_EFFECTIVENESS,
                statement="Test statement.",
                success_rate=1.5,
            )

    def test_mean_overall_score_out_of_bounds(self):
        with pytest.raises(ValueError, match="out of bounds"):
            CandidateKnowledge(
                candidate_id="cand_test_001",
                candidate_type=CandidateType.MITIGATION_EFFECTIVENESS,
                statement="Test statement.",
                mean_overall_score=2.0,
            )

    def test_statement_truncation(self):
        long_statement = "x" * 1000
        c = CandidateKnowledge(
            candidate_id="cand_test_001",
            candidate_type=CandidateType.MITIGATION_EFFECTIVENESS,
            statement=long_statement,
        )
        assert len(c.statement) <= 500

    def test_statement_secret_redaction(self):
        c = CandidateKnowledge(
            candidate_id="cand_test_001",
            candidate_type=CandidateType.MITIGATION_EFFECTIVENESS,
            statement="api_key: sk_live_abc123def456 is used here",
        )
        assert "sk_live_abc123def456" not in c.statement
        assert "[REDACTED]" in c.statement

    def test_empty_statement_rejected(self):
        with pytest.raises(ValueError):
            CandidateKnowledge(
                candidate_id="cand_test_001",
                candidate_type=CandidateType.MITIGATION_EFFECTIVENESS,
                statement="",
            )

    def test_default_status_is_proposed(self):
        c = CandidateKnowledge(
            candidate_id="cand_test_001",
            candidate_type=CandidateType.MITIGATION_EFFECTIVENESS,
            statement="Test statement.",
        )
        assert c.status == CandidateStatus.PROPOSED


class TestLearningEvidence:
    """Test LearningEvidence model validation."""

    def test_valid_evidence(self):
        ev = LearningEvidence(
            evidence_id="ev_test_001",
            mission_id="mission_test_001",
            overall_score=0.85,
        )
        assert ev.overall_score == 0.85

    def test_score_out_of_bounds(self):
        with pytest.raises(ValueError, match="out of bounds"):
            LearningEvidence(
                evidence_id="ev_test_001",
                mission_id="mission_test_001",
                overall_score=1.5,
            )

    def test_null_score_allowed(self):
        ev = LearningEvidence(
            evidence_id="ev_test_001",
            mission_id="mission_test_001",
            overall_score=None,
        )
        assert ev.overall_score is None


class TestLearningRunRequest:
    """Test LearningRunRequest model validation."""

    def test_default_request(self):
        req = LearningRunRequest()
        assert req.mission_ids == []
        assert req.dry_run is False
        assert len(req.candidate_types) == len(CandidateType)

    def test_bounded_mission_ids(self):
        # Should not raise for reasonable count
        req = LearningRunRequest(mission_ids=["m1", "m2", "m3"])
        assert len(req.mission_ids) == 3

    def test_dry_run_flag(self):
        req = LearningRunRequest(dry_run=True)
        assert req.dry_run is True


class TestRetireRequest:
    """Test RetireRequest model validation."""

    def test_valid_retire(self):
        req = RetireRequest(reason="No longer relevant.")
        assert req.reason == "No longer relevant."

    def test_empty_reason_rejected(self):
        with pytest.raises(ValueError):
            RetireRequest(reason="")

    def test_long_reason_bounded(self):
        req = RetireRequest(reason="x" * 500)
        assert len(req.reason) == 500
