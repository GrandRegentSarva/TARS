"""
Phase 9 Evaluator Tests
=========================
Tests for deterministic scoring logic.

All tests run without live services (no PX4, Phoenix, Gemini, Neo4j).
"""

from __future__ import annotations

import pytest

from tars.phase9.evaluator import (
    Evaluator,
    get_mitigation_family,
    get_root_cause_family,
    normalize_mitigation,
    normalize_root_cause,
    _contains_control_command,
)
from tars.phase9.models import ClassificationLabel, EvaluationMetric, MetricName

from .conftest import (
    make_ground_truth,
    make_ground_truth_failed,
    make_ground_truth_no_evidence,
    make_ground_truth_nominal,
    make_incident,
    make_reasoning,
    make_reasoning_partial_cause,
    make_reasoning_with_control_command,
    make_reasoning_wrong_cause,
)


# =============================================================================
# Normalization Tests
# =============================================================================

class TestNormalization:
    """Test root-cause and mitigation normalization."""

    def test_normalize_exact(self):
        """Exact canonical name should be unchanged."""
        assert normalize_root_cause("gps_interference") == "gps_interference"

    def test_normalize_alias(self):
        """Known alias should resolve to canonical form."""
        assert normalize_root_cause("gps_drift") == "gps_interference"
        assert normalize_root_cause("localization_loss") == "gps_interference"
        assert normalize_root_cause("wind_disturbance") == "environmental_wind"
        assert normalize_root_cause("battery_sag") == "power_instability"

    def test_normalize_case_insensitive(self):
        """Normalization should be case-insensitive."""
        assert normalize_root_cause("GPS_Interference") == "gps_interference"
        assert normalize_root_cause("GPS_DRIFT") == "gps_interference"

    def test_normalize_whitespace(self):
        """Whitespace should be normalized to underscores."""
        assert normalize_root_cause("gps interference") == "gps_interference"
        assert normalize_root_cause("  gps  drift  ") == "gps_interference"

    def test_normalize_unknown_passthrough(self):
        """Unknown root causes should pass through normalized."""
        assert normalize_root_cause("unknown_cause") == "unknown_cause"

    def test_normalize_mitigation(self):
        """Mitigation normalization should work."""
        assert normalize_mitigation("Switch to Visual Odometry") == "switch_to_visual_odometry"

    def test_get_root_cause_family(self):
        """Root-cause family lookup should work."""
        assert get_root_cause_family("gps_interference") == "navigation"
        assert get_root_cause_family("power_instability") == "power"
        assert get_root_cause_family("environmental_wind") == "environmental"
        assert get_root_cause_family("actuator_failure") == "mechanical"
        assert get_root_cause_family("sensor_failure") == "sensor"
        assert get_root_cause_family("link_failure") == "communication"
        assert get_root_cause_family("operator_error") == "operator"

    def test_get_root_cause_family_unknown(self):
        """Unknown root cause should return None family."""
        assert get_root_cause_family("unknown_cause") is None

    def test_get_mitigation_family(self):
        """Mitigation family lookup should work."""
        assert get_mitigation_family("switch_to_visual_odometry") == "navigation_switch"
        assert get_mitigation_family("return_to_launch") == "return_home"

    def test_contains_control_command(self):
        """Control command detection should work."""
        assert _contains_control_command("Execute RTL immediately") is True
        assert _contains_control_command("arm the drone") is True
        assert _contains_control_command("land now") is True
        assert _contains_control_command("Consider monitoring GPS quality") is False
        assert _contains_control_command("Switch navigation source") is False


# =============================================================================
# Root-Cause Scoring Tests
# =============================================================================

class TestRootCauseScoring:
    """Test root-cause accuracy scoring."""

    def test_exact_match_scores_one(self, evaluator):
        """Exact normalized match should score 1.0."""
        reasoning = make_reasoning(root_cause="gps_interference")
        gt = make_ground_truth(root_cause="gps_interference")
        metric = evaluator.score_root_cause(reasoning, gt)
        assert metric.score == 1.0
        assert metric.label == ClassificationLabel.CORRECT

    def test_alias_match_scores_one(self, evaluator):
        """Known alias match should score 1.0."""
        reasoning = make_reasoning(root_cause="gps_drift")
        gt = make_ground_truth(root_cause="gps_interference")
        metric = evaluator.score_root_cause(reasoning, gt)
        assert metric.score == 1.0
        assert metric.label == ClassificationLabel.CORRECT

    def test_same_family_scores_half(self, evaluator):
        """Same root-cause family should score 0.5."""
        reasoning = make_reasoning(root_cause="navigation_instability")
        gt = make_ground_truth(root_cause="gps_interference")
        metric = evaluator.score_root_cause(reasoning, gt)
        assert metric.score == 0.5
        assert metric.label == ClassificationLabel.PARTIALLY_CORRECT

    def test_mismatch_scores_zero(self, evaluator):
        """Different root cause should score 0.0."""
        reasoning = make_reasoning_wrong_cause()
        gt = make_ground_truth(root_cause="gps_interference")
        metric = evaluator.score_root_cause(reasoning, gt)
        assert metric.score == 0.0
        assert metric.label == ClassificationLabel.INCORRECT

    def test_missing_ground_truth_insufficient(self, evaluator):
        """Missing ground truth should return insufficient evidence."""
        reasoning = make_reasoning()
        gt = make_ground_truth_no_evidence()
        metric = evaluator.score_root_cause(reasoning, gt)
        assert metric.score is None
        assert metric.label == ClassificationLabel.INSUFFICIENT_EVIDENCE

    def test_missing_gt_root_cause_insufficient(self, evaluator):
        """Ground truth with no root cause should return insufficient."""
        reasoning = make_reasoning()
        gt = make_ground_truth(root_cause=None)
        # Need to set root_cause to None after creation
        gt.label.root_cause = None
        metric = evaluator.score_root_cause(reasoning, gt)
        assert metric.score is None
        assert metric.label == ClassificationLabel.INSUFFICIENT_EVIDENCE

    def test_empty_prediction_scores_zero(self, evaluator):
        """Empty predicted root cause should score 0.0."""
        reasoning = make_reasoning(root_cause="")
        gt = make_ground_truth(root_cause="gps_interference")
        metric = evaluator.score_root_cause(reasoning, gt)
        assert metric.score == 0.0
        assert metric.label == ClassificationLabel.INCORRECT


# =============================================================================
# Recommendation Scoring Tests
# =============================================================================

class TestRecommendationScoring:
    """Test recommendation accuracy scoring."""

    def test_exact_match_scores_one(self, evaluator):
        """Exact mitigation match should score 1.0."""
        reasoning = make_reasoning(
            recommendation="switch_to_visual_odometry"
        )
        gt = make_ground_truth(preferred_mitigation="switch_to_visual_odometry")
        metric = evaluator.score_recommendation(reasoning, gt)
        assert metric.score == 1.0
        assert metric.label == ClassificationLabel.CORRECT

    def test_contains_preferred_scores_one(self, evaluator):
        """Recommendation containing preferred mitigation should score 1.0."""
        reasoning = make_reasoning(
            recommendation="We should switch to visual odometry immediately"
        )
        gt = make_ground_truth(
            preferred_mitigation="switch_to_visual_odometry"
        )
        metric = evaluator.score_recommendation(reasoning, gt)
        assert metric.score == 1.0

    def test_natural_advisory_text_matches_via_tokens(self, evaluator):
        """Natural advisory text should match via word-level tokens."""
        reasoning = make_reasoning(
            recommendation="Consider switching to visual odometry when GPS degrades"
        )
        gt = make_ground_truth(
            preferred_mitigation="switch_to_visual_odometry"
        )
        metric = evaluator.score_recommendation(reasoning, gt)
        # Token matching: "switch", "visual", "odometry" all present
        # in "consider_switching_to_visual_odometry_when_gps_degrades"
        # after removing stop words
        assert metric.score == 1.0
        assert metric.label == ClassificationLabel.CORRECT

    def test_same_family_scores_half(self, evaluator):
        """Same mitigation family should score 0.5."""
        reasoning = make_reasoning(
            recommendation="enable_backup_navigation"
        )
        gt = make_ground_truth(
            preferred_mitigation="switch_to_visual_odometry"
        )
        metric = evaluator.score_recommendation(reasoning, gt)
        assert metric.score == 0.5
        assert metric.label == ClassificationLabel.PARTIALLY_CORRECT

    def test_unrelated_scores_zero(self, evaluator):
        """Unrelated recommendation should score 0.0."""
        reasoning = make_reasoning(
            recommendation="Monitor battery levels closely"
        )
        gt = make_ground_truth(
            preferred_mitigation="switch_to_visual_odometry"
        )
        metric = evaluator.score_recommendation(reasoning, gt)
        assert metric.score == 0.0
        assert metric.label == ClassificationLabel.INCORRECT

    def test_control_command_scores_zero(self, evaluator):
        """Recommendation with control command should score 0.0."""
        reasoning = make_reasoning_with_control_command()
        gt = make_ground_truth()
        metric = evaluator.score_recommendation(reasoning, gt)
        assert metric.score == 0.0
        assert "flight-control command" in metric.explanation

    def test_missing_preferred_mitigation_insufficient(self, evaluator):
        """Missing preferred mitigation should return insufficient."""
        reasoning = make_reasoning()
        gt = make_ground_truth(preferred_mitigation=None)
        gt.label.preferred_mitigation = None
        metric = evaluator.score_recommendation(reasoning, gt)
        assert metric.score is None
        assert metric.label == ClassificationLabel.INSUFFICIENT_EVIDENCE

    def test_missing_ground_truth_insufficient(self, evaluator):
        """Missing ground truth should return insufficient."""
        reasoning = make_reasoning()
        gt = make_ground_truth_no_evidence()
        metric = evaluator.score_recommendation(reasoning, gt)
        assert metric.score is None
        assert metric.label == ClassificationLabel.INSUFFICIENT_EVIDENCE


# =============================================================================
# Consistency Scoring Tests
# =============================================================================

class TestConsistencyScoring:
    """Test response consistency scoring."""

    def test_insufficient_cases(self, evaluator):
        """Fewer than min cases should return insufficient."""
        reasoning = make_reasoning()
        metric = evaluator.score_consistency(reasoning, [])
        assert metric.score is None
        assert metric.label == ClassificationLabel.INSUFFICIENT_EVIDENCE

    def test_none_similar_evaluations(self, evaluator):
        """None similar evaluations should return insufficient."""
        reasoning = make_reasoning()
        metric = evaluator.score_consistency(reasoning, None)
        assert metric.score is None
        assert metric.label == ClassificationLabel.INSUFFICIENT_EVIDENCE

    def test_high_consistency(self, evaluator):
        """All similar cases with high scores should give high consistency."""
        reasoning = make_reasoning()
        similar = [
            {"root_cause_score": 1.0, "recommendation_score": 1.0}
            for _ in range(5)
        ]
        metric = evaluator.score_consistency(reasoning, similar)
        assert metric.score is not None
        assert metric.score >= 0.8
        assert metric.label == ClassificationLabel.CORRECT

    def test_low_consistency(self, evaluator):
        """All similar cases with low scores should give low consistency."""
        reasoning = make_reasoning()
        similar = [
            {"root_cause_score": 0.0, "recommendation_score": 0.0}
            for _ in range(5)
        ]
        metric = evaluator.score_consistency(reasoning, similar)
        assert metric.score is not None
        assert metric.score < 0.5

    def test_mixed_consistency(self, evaluator):
        """Mixed scores should give partial consistency."""
        reasoning = make_reasoning()
        similar = [
            {"root_cause_score": 1.0, "recommendation_score": 1.0},
            {"root_cause_score": 0.0, "recommendation_score": 0.0},
            {"root_cause_score": 1.0, "recommendation_score": 0.5},
        ]
        metric = evaluator.score_consistency(reasoning, similar)
        assert metric.score is not None
        assert 0.0 < metric.score < 1.0


# =============================================================================
# False Positive Tests
# =============================================================================

class TestFalsePositiveScoring:
    """Test false-positive detection."""

    def test_no_false_positive(self, evaluator):
        """Normal case should not be a false positive."""
        reasoning = make_reasoning()
        gt = make_ground_truth()
        metric = evaluator.score_false_positive(reasoning, gt)
        assert metric is not None
        assert metric.score == 1.0
        assert metric.label == ClassificationLabel.CORRECT

    def test_false_positive_nominal_outcome(self, evaluator):
        """Reasoning claiming problem with nominal outcome is false positive."""
        reasoning = make_reasoning(root_cause="gps_interference")
        gt = make_ground_truth_nominal()
        metric = evaluator.score_false_positive(reasoning, gt)
        assert metric is not None
        assert metric.score == 0.0
        assert metric.label == ClassificationLabel.INCORRECT

    def test_no_evidence_returns_none(self, evaluator):
        """No evidence should return None."""
        reasoning = make_reasoning()
        gt = make_ground_truth_no_evidence()
        metric = evaluator.score_false_positive(reasoning, gt)
        assert metric is None


# =============================================================================
# False Negative Tests
# =============================================================================

class TestFalseNegativeScoring:
    """Test false-negative detection."""

    def test_no_false_negative(self, evaluator):
        """Normal case should not be a false negative."""
        reasoning = make_reasoning()
        gt = make_ground_truth()
        incidents = [make_incident()]
        reasoning_results = [make_reasoning()]
        metric = evaluator.score_false_negative(
            "mission_test_001", incidents, reasoning_results, gt
        )
        assert metric is not None
        assert metric.label == ClassificationLabel.CORRECT

    def test_false_negative_no_incidents(self, evaluator):
        """Failed outcome with no incidents is a false negative."""
        gt = make_ground_truth_failed()
        metric = evaluator.score_false_negative(
            "mission_test_001", [], [], gt
        )
        assert metric is not None
        assert metric.score == 0.0
        assert metric.label == ClassificationLabel.INCORRECT

    def test_false_negative_no_reasoning(self, evaluator):
        """Incidents without reasoning is a false negative."""
        gt = make_ground_truth_failed()
        incidents = [make_incident()]
        metric = evaluator.score_false_negative(
            "mission_test_001", incidents, [], gt
        )
        assert metric is not None
        assert metric.score == 0.0
        assert metric.label == ClassificationLabel.INCORRECT

    def test_no_evidence_returns_none(self, evaluator):
        """No evidence should return None."""
        gt = make_ground_truth_no_evidence()
        metric = evaluator.score_false_negative(
            "mission_test_001", [], [], gt
        )
        assert metric is None


# =============================================================================
# Overall Score Tests
# =============================================================================

class TestOverallScore:
    """Test weighted overall score computation."""

    def test_all_perfect_scores(self, evaluator):
        """All perfect scores should give overall near 1.0."""
        metrics = [
            EvaluationMetric(
                name=MetricName.ROOT_CAUSE_ACCURACY,
                score=1.0,
                label=ClassificationLabel.CORRECT,
                evidence=["operator_label"],
                explanation="Match.",
            ),
            EvaluationMetric(
                name=MetricName.RECOMMENDATION_ACCURACY,
                score=1.0,
                label=ClassificationLabel.CORRECT,
                evidence=["operator_label"],
                explanation="Match.",
            ),
            EvaluationMetric(
                name=MetricName.RESPONSE_CONSISTENCY,
                score=1.0,
                label=ClassificationLabel.CORRECT,
                evidence=["historical_consistency"],
                explanation="Consistent.",
            ),
            EvaluationMetric(
                name=MetricName.FALSE_POSITIVE,
                score=1.0,
                label=ClassificationLabel.CORRECT,
                evidence=["operator_label"],
                explanation="Not FP.",
            ),
            EvaluationMetric(
                name=MetricName.FALSE_NEGATIVE,
                score=1.0,
                label=ClassificationLabel.CORRECT,
                evidence=["operator_label"],
                explanation="Not FN.",
            ),
        ]
        overall = evaluator.compute_overall_score(metrics)
        assert overall is not None
        assert abs(overall - 1.0) < 0.01

    def test_all_zero_scores(self, evaluator):
        """All zero scores should give overall 0.0."""
        metrics = [
            EvaluationMetric(
                name=MetricName.ROOT_CAUSE_ACCURACY,
                score=0.0,
                label=ClassificationLabel.INCORRECT,
                evidence=["operator_label"],
                explanation="Mismatch.",
            ),
            EvaluationMetric(
                name=MetricName.RECOMMENDATION_ACCURACY,
                score=0.0,
                label=ClassificationLabel.INCORRECT,
                evidence=["operator_label"],
                explanation="Mismatch.",
            ),
        ]
        overall = evaluator.compute_overall_score(metrics)
        assert overall is not None
        assert overall == 0.0

    def test_insufficient_evidence_excluded(self, evaluator):
        """Insufficient evidence metrics should be excluded from denominator."""
        metrics = [
            EvaluationMetric(
                name=MetricName.ROOT_CAUSE_ACCURACY,
                score=1.0,
                label=ClassificationLabel.CORRECT,
                evidence=["operator_label"],
                explanation="Match.",
            ),
            EvaluationMetric(
                name=MetricName.RECOMMENDATION_ACCURACY,
                score=None,
                label=ClassificationLabel.INSUFFICIENT_EVIDENCE,
                evidence=[],
                explanation="No evidence.",
            ),
        ]
        overall = evaluator.compute_overall_score(metrics)
        assert overall is not None
        assert overall == 1.0  # Only root cause counted

    def test_all_insufficient_returns_none(self, evaluator):
        """All insufficient evidence should return None overall."""
        metrics = [
            EvaluationMetric(
                name=MetricName.ROOT_CAUSE_ACCURACY,
                score=None,
                label=ClassificationLabel.INSUFFICIENT_EVIDENCE,
                evidence=[],
                explanation="No evidence.",
            ),
        ]
        overall = evaluator.compute_overall_score(metrics)
        assert overall is None

    def test_empty_metrics_returns_none(self, evaluator):
        """Empty metrics list should return None."""
        overall = evaluator.compute_overall_score([])
        assert overall is None


# =============================================================================
# Full Evaluate Tests
# =============================================================================

class TestFullEvaluate:
    """Test the full evaluate method."""

    def test_evaluate_produces_metrics(self, evaluator):
        """Full evaluation should produce metrics."""
        reasoning = make_reasoning()
        gt = make_ground_truth()
        metrics = evaluator.evaluate(
            reasoning=reasoning,
            ground_truth=gt,
            evaluate_consistency=False,
        )
        assert len(metrics) >= 2  # root cause + recommendation + optional FP
        names = [m.name for m in metrics]
        assert MetricName.ROOT_CAUSE_ACCURACY in names
        assert MetricName.RECOMMENDATION_ACCURACY in names

    def test_evaluate_with_consistency(self, evaluator):
        """Evaluation with consistency should include consistency metric."""
        reasoning = make_reasoning()
        gt = make_ground_truth()
        metrics = evaluator.evaluate(
            reasoning=reasoning,
            ground_truth=gt,
            evaluate_consistency=True,
        )
        names = [m.name for m in metrics]
        assert MetricName.RESPONSE_CONSISTENCY in names
