"""
Phase 9 Model Tests
=====================
Tests for evaluation models, enums, and validation.
"""

from __future__ import annotations

import pytest

from tars.phase9.models import (
    BatchEvaluationRequest,
    ClassificationLabel,
    EvaluationMetric,
    EvaluationRequest,
    EvaluationResult,
    EvidenceLevel,
    GroundTruthLabel,
    GroundTruthLabelCreate,
    GroundTruthPayload,
    GroundTruthSource,
    MetricName,
    _redact_secrets,
    _truncate_and_redact,
)


class TestEnums:
    """Test enum values and membership."""

    def test_classification_labels(self):
        """All classification labels should be defined."""
        assert ClassificationLabel.CORRECT == "correct"
        assert ClassificationLabel.PARTIALLY_CORRECT == "partially_correct"
        assert ClassificationLabel.INCORRECT == "incorrect"
        assert ClassificationLabel.INSUFFICIENT_EVIDENCE == "insufficient_evidence"
        assert ClassificationLabel.NOT_APPLICABLE == "not_applicable"

    def test_evidence_levels(self):
        """All evidence levels should be defined."""
        assert EvidenceLevel.OPERATOR_LABEL == "operator_label"
        assert EvidenceLevel.MISSION_OUTCOME == "mission_outcome"
        assert EvidenceLevel.DETERMINISTIC_INCIDENT == "deterministic_incident"
        assert EvidenceLevel.HISTORICAL_CONSISTENCY == "historical_consistency"
        assert EvidenceLevel.TRACE_METADATA == "trace_metadata"

    def test_ground_truth_sources(self):
        """All ground-truth sources should be defined."""
        assert GroundTruthSource.OPERATOR_LABEL == "operator_label"
        assert GroundTruthSource.MISSION_OUTCOME == "mission_outcome"
        assert GroundTruthSource.SYNTHETIC_TEST_CASE == "synthetic_test_case"
        assert GroundTruthSource.DETERMINISTIC_RULE == "deterministic_rule"

    def test_metric_names(self):
        """All metric names should be defined."""
        assert MetricName.ROOT_CAUSE_ACCURACY == "root_cause_accuracy"
        assert MetricName.RECOMMENDATION_ACCURACY == "recommendation_accuracy"
        assert MetricName.RESPONSE_CONSISTENCY == "response_consistency"
        assert MetricName.FALSE_POSITIVE == "false_positive"
        assert MetricName.FALSE_NEGATIVE == "false_negative"
        assert MetricName.OVERALL_SCORE == "overall_score"


class TestEvaluationMetric:
    """Test EvaluationMetric validation."""

    def test_valid_metric(self):
        """Valid metric should be created."""
        m = EvaluationMetric(
            name=MetricName.ROOT_CAUSE_ACCURACY,
            score=0.85,
            label=ClassificationLabel.CORRECT,
            evidence=["operator_label"],
            explanation="Root cause matched.",
        )
        assert m.score == 0.85
        assert m.label == ClassificationLabel.CORRECT

    def test_null_score_allowed(self):
        """Null score should be allowed for insufficient evidence."""
        m = EvaluationMetric(
            name=MetricName.ROOT_CAUSE_ACCURACY,
            score=None,
            label=ClassificationLabel.INSUFFICIENT_EVIDENCE,
            evidence=[],
            explanation="No ground truth available.",
        )
        assert m.score is None

    def test_score_below_zero_rejected(self):
        """Score below 0.0 should be rejected."""
        with pytest.raises(ValueError, match="out of bounds"):
            EvaluationMetric(
                name=MetricName.ROOT_CAUSE_ACCURACY,
                score=-0.1,
                label=ClassificationLabel.INCORRECT,
                evidence=[],
                explanation="Test.",
            )

    def test_score_above_one_rejected(self):
        """Score above 1.0 should be rejected."""
        with pytest.raises(ValueError, match="out of bounds"):
            EvaluationMetric(
                name=MetricName.ROOT_CAUSE_ACCURACY,
                score=1.5,
                label=ClassificationLabel.CORRECT,
                evidence=[],
                explanation="Test.",
            )

    def test_score_zero_allowed(self):
        """Score of 0.0 should be allowed."""
        m = EvaluationMetric(
            name=MetricName.ROOT_CAUSE_ACCURACY,
            score=0.0,
            label=ClassificationLabel.INCORRECT,
            evidence=[],
            explanation="Mismatch.",
        )
        assert m.score == 0.0

    def test_score_one_allowed(self):
        """Score of 1.0 should be allowed."""
        m = EvaluationMetric(
            name=MetricName.ROOT_CAUSE_ACCURACY,
            score=1.0,
            label=ClassificationLabel.CORRECT,
            evidence=[],
            explanation="Exact match.",
        )
        assert m.score == 1.0

    def test_explanation_truncated(self):
        """Overlong explanations should be truncated."""
        long_text = "x" * 5000
        m = EvaluationMetric(
            name=MetricName.ROOT_CAUSE_ACCURACY,
            score=1.0,
            label=ClassificationLabel.CORRECT,
            evidence=[],
            explanation=long_text,
        )
        assert len(m.explanation) <= 2000


class TestEvaluationResult:
    """Test EvaluationResult validation."""

    def test_advisory_only_must_be_true(self):
        """advisory_only=False should be rejected."""
        with pytest.raises(ValueError, match="advisory_only must always be True"):
            EvaluationResult(
                evaluation_id="eval_test",
                mission_id="mission_test",
                evaluator_version="v1.0",
                advisory_only=False,
            )

    def test_advisory_only_true_accepted(self):
        """advisory_only=True should be accepted."""
        r = EvaluationResult(
            evaluation_id="eval_test",
            mission_id="mission_test",
            evaluator_version="v1.0",
            advisory_only=True,
        )
        assert r.advisory_only is True

    def test_overall_score_bounds(self):
        """Overall score outside [0.0, 1.0] should be rejected."""
        with pytest.raises(ValueError, match="out of bounds"):
            EvaluationResult(
                evaluation_id="eval_test",
                mission_id="mission_test",
                evaluator_version="v1.0",
                overall_score=1.5,
            )

    def test_null_overall_score_allowed(self):
        """Null overall score should be allowed."""
        r = EvaluationResult(
            evaluation_id="eval_test",
            mission_id="mission_test",
            evaluator_version="v1.0",
            overall_score=None,
        )
        assert r.overall_score is None


class TestSecretRedaction:
    """Test secret redaction in explanations."""

    def test_api_key_redacted(self):
        """API keys should be redacted."""
        text = "Error with api_key=sk-abc123xyz"
        result = _redact_secrets(text)
        assert "sk-abc123xyz" not in result
        assert "REDACTED" in result

    def test_bearer_token_redacted(self):
        """Bearer tokens should be redacted."""
        text = "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.test"
        result = _redact_secrets(text)
        assert "eyJhbGciOiJIUzI1NiJ9" not in result

    def test_normal_text_unchanged(self):
        """Normal text should not be redacted."""
        text = "Root cause matched accepted label."
        result = _redact_secrets(text)
        assert result == text

    def test_truncate_and_redact(self):
        """Text should be both truncated and redacted."""
        text = "api_key=secret123 " + "x" * 3000
        result = _truncate_and_redact(text, 100)
        assert len(result) <= 100
        assert "secret123" not in result


class TestEvaluationRequest:
    """Test EvaluationRequest validation."""

    def test_minimal_request(self):
        """Minimal request with just mission_id should work."""
        r = EvaluationRequest(mission_id="mission_001")
        assert r.mission_id == "mission_001"
        assert r.incident_id is None
        assert r.overwrite is False

    def test_full_request(self):
        """Full request with all fields should work."""
        r = EvaluationRequest(
            mission_id="mission_001",
            incident_id="inc_001",
            reasoning_id="reason_001",
            trace_id="trace_001",
            ground_truth=GroundTruthPayload(
                root_cause="gps_interference",
                preferred_mitigation="switch_to_visual_odometry",
                outcome="recovered",
            ),
            evaluate_consistency=True,
            overwrite=False,
        )
        assert r.ground_truth is not None
        assert r.ground_truth.root_cause == "gps_interference"

    def test_empty_mission_id_rejected(self):
        """Empty mission_id should be rejected."""
        with pytest.raises(ValueError):
            EvaluationRequest(mission_id="")


class TestBatchEvaluationRequest:
    """Test BatchEvaluationRequest validation."""

    def test_valid_batch(self):
        """Valid batch should be accepted."""
        targets = [
            EvaluationRequest(mission_id=f"mission_{i}")
            for i in range(5)
        ]
        batch = BatchEvaluationRequest(targets=targets)
        assert len(batch.targets) == 5

    def test_empty_batch_rejected(self):
        """Empty batch should be rejected."""
        with pytest.raises(ValueError):
            BatchEvaluationRequest(targets=[])


class TestGroundTruthLabel:
    """Test GroundTruthLabel validation."""

    def test_valid_label(self):
        """Valid label should be created."""
        label = GroundTruthLabel(
            root_cause="gps_interference",
            preferred_mitigation="switch_to_visual_odometry",
            outcome="recovered",
            source=GroundTruthSource.OPERATOR_LABEL,
            labeled_by="operator",
        )
        assert label.source == GroundTruthSource.OPERATOR_LABEL

    def test_label_with_no_root_cause(self):
        """Label without root cause should be valid."""
        label = GroundTruthLabel(
            outcome="recovered",
            source=GroundTruthSource.MISSION_OUTCOME,
        )
        assert label.root_cause is None

    def test_label_create_model(self):
        """GroundTruthLabelCreate should validate."""
        create = GroundTruthLabelCreate(
            mission_id="mission_001",
            root_cause="gps_interference",
            source=GroundTruthSource.OPERATOR_LABEL,
        )
        assert create.mission_id == "mission_001"
