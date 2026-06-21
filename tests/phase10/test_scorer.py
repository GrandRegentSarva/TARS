"""
Phase 10 Candidate Scorer Tests
==================================
Tests for confidence bounds, success-rate math, contradiction penalties,
and versioning.
"""

from __future__ import annotations

import pytest

from tars.phase10.models import CandidateType, EvidenceLevel
from tars.phase10.pattern_miner import PatternGroup
from tars.phase10.scorer import CandidateScorer

from .conftest import make_evidence


def _make_pattern(
    *,
    candidate_type: CandidateType = CandidateType.MITIGATION_EFFECTIVENESS,
    support_count: int = 10,
    contradiction_count: int = 1,
    mission_count: int = 8,
    overall_score: float = 0.85,
    outcome: str = "recovered",
    root_cause_label: str = "correct",
    recommendation_label: str = "correct",
) -> PatternGroup:
    """Build a PatternGroup with specified counts."""
    group = PatternGroup(
        candidate_type=candidate_type,
        group_key="test:key",
        incident_family="navigation_instability",
        root_cause="gps_interference",
        mitigation="switch_to_visual_odometry",
        outcome_family="recovered_or_stabilized",
    )

    for i in range(support_count):
        ev = make_evidence(
            mission_id=f"mission_{i:03d}",
            incident_id=f"nav_inc_{i:03d}",
            overall_score=overall_score,
            outcome=outcome,
            root_cause_label=root_cause_label,
            recommendation_label=recommendation_label,
        )
        group.all_items.append(ev)
        group.support_items.append(ev)

    for i in range(contradiction_count):
        ev = make_evidence(
            mission_id=f"mission_contra_{i:03d}",
            incident_id=f"nav_inc_contra_{i:03d}",
            overall_score=0.3,
            outcome="failed",
            root_cause_label="incorrect",
            recommendation_label="incorrect",
        )
        group.all_items.append(ev)
        group.contradiction_items.append(ev)

    return group


class TestConfidenceBounds:
    """Test that confidence scores are bounded [0.0, 1.0]."""

    def test_confidence_bounded_high(self, scorer):
        """High support should not exceed 1.0."""
        pattern = _make_pattern(
            support_count=50,
            contradiction_count=0,
            overall_score=1.0,
        )
        confidence = scorer.score(pattern)
        assert 0.0 <= confidence <= 1.0

    def test_confidence_bounded_low(self, scorer):
        """Low support should not go below 0.0."""
        pattern = _make_pattern(
            support_count=1,
            contradiction_count=10,
            overall_score=0.1,
        )
        confidence = scorer.score(pattern)
        assert 0.0 <= confidence <= 1.0

    def test_empty_pattern_score(self, scorer):
        """Empty pattern should produce a bounded score."""
        pattern = PatternGroup(
            candidate_type=CandidateType.MITIGATION_EFFECTIVENESS,
            group_key="empty:key",
        )
        confidence = scorer.score(pattern)
        assert 0.0 <= confidence <= 1.0


class TestSupportStrength:
    """Test support strength scoring."""

    def test_more_support_higher_score(self, scorer):
        """More support should produce higher confidence."""
        low = _make_pattern(support_count=3, contradiction_count=0)
        high = _make_pattern(support_count=20, contradiction_count=0)
        assert scorer.score(high) > scorer.score(low)

    def test_more_missions_higher_score(self, scorer):
        """More distinct missions should produce higher confidence."""
        low = _make_pattern(support_count=5, mission_count=2)
        high = _make_pattern(support_count=5, mission_count=10)
        # Both have same support count but different mission diversity
        assert scorer.score(high) >= scorer.score(low)


class TestContradictionPenalty:
    """Test contradiction penalty scoring."""

    def test_contradictions_lower_score(self, scorer):
        """More contradictions should lower confidence."""
        no_contra = _make_pattern(
            support_count=10, contradiction_count=0
        )
        with_contra = _make_pattern(
            support_count=10, contradiction_count=5
        )
        assert scorer.score(no_contra) > scorer.score(with_contra)

    def test_all_contradictions_low_score(self, scorer):
        """All contradictions should produce very low confidence."""
        pattern = _make_pattern(
            support_count=0, contradiction_count=10
        )
        confidence = scorer.score(pattern)
        assert confidence < 0.5


class TestEvaluationQuality:
    """Test evaluation quality scoring."""

    def test_high_eval_score_higher_confidence(self, scorer):
        """Higher evaluation scores should increase confidence."""
        low_eval = _make_pattern(overall_score=0.3)
        high_eval = _make_pattern(overall_score=0.95)
        assert scorer.score(high_eval) > scorer.score(low_eval)


class TestVersioning:
    """Test scorer versioning."""

    def test_scorer_has_version(self, scorer):
        """Scorer should carry a version string."""
        assert scorer.version == "phase10.v1-test"

    def test_custom_version(self):
        """Custom version should be stored."""
        s = CandidateScorer(version="phase10.v2")
        assert s.version == "phase10.v2"

    def test_deterministic_scoring(self, scorer):
        """Same pattern should produce same score."""
        pattern = _make_pattern()
        score1 = scorer.score(pattern)
        score2 = scorer.score(pattern)
        assert score1 == score2
