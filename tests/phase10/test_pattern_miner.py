"""
Phase 10 Pattern Miner Tests
===============================
Tests for deterministic grouping, support/contradiction counting,
and suppression reasons.
"""

from __future__ import annotations

import pytest

from tars.phase10.models import CandidateType
from tars.phase10.pattern_miner import PatternMiner

from .conftest import make_evidence, make_evidence_set


class TestMitigationEffectiveness:
    """Test mitigation effectiveness pattern mining."""

    def test_basic_mitigation_pattern(self, pattern_miner):
        """Sufficient evidence should produce a mitigation pattern."""
        evidence = make_evidence_set(
            count=6,
            root_cause="gps_interference",
            mitigation="switch_to_visual_odometry",
            outcome="recovered",
        )
        patterns, suppressions = pattern_miner.mine_patterns(
            evidence,
            candidate_types=[CandidateType.MITIGATION_EFFECTIVENESS],
        )
        assert len(patterns) >= 1
        p = patterns[0]
        assert p.candidate_type == CandidateType.MITIGATION_EFFECTIVENESS
        assert p.root_cause == "gps_interference"
        assert p.mitigation == "switch_to_visual_odometry"
        assert p.support_count > 0

    def test_insufficient_cases_suppressed(self):
        """Below minimum cases should be suppressed."""
        miner = PatternMiner(
            min_evaluated_cases=10,
            min_distinct_missions=2,
        )
        evidence = make_evidence_set(count=3)
        patterns, suppressions = miner.mine_patterns(
            evidence,
            candidate_types=[CandidateType.MITIGATION_EFFECTIVENESS],
        )
        assert len(patterns) == 0
        assert len(suppressions) > 0
        assert any("minimum evaluated cases" in s.reason for s in suppressions)

    def test_insufficient_missions_suppressed(self):
        """Below minimum distinct missions should be suppressed."""
        miner = PatternMiner(
            min_evaluated_cases=2,
            min_distinct_missions=5,
        )
        # All from same mission
        evidence = [
            make_evidence(
                mission_id="mission_same",
                incident_id=f"nav_inc_{i:03d}",
            )
            for i in range(4)
        ]
        patterns, suppressions = miner.mine_patterns(
            evidence,
            candidate_types=[CandidateType.MITIGATION_EFFECTIVENESS],
        )
        assert len(patterns) == 0
        assert any("minimum distinct missions" in s.reason for s in suppressions)

    def test_low_success_rate_suppressed(self):
        """Low success rate should suppress mitigation patterns."""
        miner = PatternMiner(
            min_evaluated_cases=3,
            min_distinct_missions=2,
            min_success_rate=0.80,
        )
        # Mix of good and bad outcomes
        evidence = []
        for i in range(5):
            evidence.append(
                make_evidence(
                    mission_id=f"mission_{i:03d}",
                    incident_id=f"nav_inc_{i:03d}",
                    outcome="failed" if i < 3 else "recovered",
                    recommendation_label="incorrect" if i < 3 else "correct",
                )
            )
        patterns, suppressions = miner.mine_patterns(
            evidence,
            candidate_types=[CandidateType.MITIGATION_EFFECTIVENESS],
        )
        assert len(patterns) == 0
        assert any("success rate" in s.reason for s in suppressions)

    def test_contradictions_counted_separately(self, pattern_miner):
        """Contradictions should be counted separately from support."""
        evidence = []
        # 5 supporting
        for i in range(5):
            evidence.append(
                make_evidence(
                    mission_id=f"mission_sup_{i:03d}",
                    incident_id=f"nav_inc_sup_{i:03d}",
                    outcome="recovered",
                    recommendation_label="correct",
                )
            )
        # 1 contradicting
        evidence.append(
            make_evidence(
                mission_id="mission_contra_001",
                incident_id="nav_inc_contra_001",
                outcome="failed",
                recommendation_label="incorrect",
            )
        )
        patterns, _ = pattern_miner.mine_patterns(
            evidence,
            candidate_types=[CandidateType.MITIGATION_EFFECTIVENESS],
        )
        assert len(patterns) >= 1
        p = patterns[0]
        assert p.support_count == 5
        assert p.contradiction_count == 1

    def test_no_root_cause_skipped(self, pattern_miner):
        """Evidence without root cause should be skipped."""
        evidence = [
            make_evidence(
                mission_id=f"mission_{i:03d}",
                incident_id=f"nav_inc_{i:03d}",
                root_cause=None,
            )
            for i in range(5)
        ]
        patterns, _ = pattern_miner.mine_patterns(
            evidence,
            candidate_types=[CandidateType.MITIGATION_EFFECTIVENESS],
        )
        assert len(patterns) == 0


class TestRootCausePattern:
    """Test root-cause pattern mining."""

    def test_basic_root_cause_pattern(self, pattern_miner):
        """Sufficient evidence should produce a root cause pattern."""
        evidence = make_evidence_set(
            count=6,
            root_cause="gps_interference",
            root_cause_label="correct",
        )
        patterns, _ = pattern_miner.mine_patterns(
            evidence,
            candidate_types=[CandidateType.ROOT_CAUSE_PATTERN],
        )
        assert len(patterns) >= 1
        p = patterns[0]
        assert p.candidate_type == CandidateType.ROOT_CAUSE_PATTERN
        assert p.root_cause == "gps_interference"


class TestFalsePositivePattern:
    """Test false-positive pattern mining."""

    def test_false_positive_pattern(self, pattern_miner):
        """Repeated false positives should produce a pattern."""
        evidence = make_evidence_set(
            count=6,
            false_positive=True,
        )
        patterns, _ = pattern_miner.mine_patterns(
            evidence,
            candidate_types=[CandidateType.FALSE_POSITIVE_PATTERN],
        )
        assert len(patterns) >= 1
        p = patterns[0]
        assert p.candidate_type == CandidateType.FALSE_POSITIVE_PATTERN

    def test_no_false_positives_no_pattern(self, pattern_miner):
        """No false positives should produce no pattern."""
        evidence = make_evidence_set(count=6, false_positive=False)
        patterns, _ = pattern_miner.mine_patterns(
            evidence,
            candidate_types=[CandidateType.FALSE_POSITIVE_PATTERN],
        )
        assert len(patterns) == 0


class TestFalseNegativePattern:
    """Test false-negative pattern mining."""

    def test_false_negative_pattern(self, pattern_miner):
        """Repeated false negatives should produce a pattern."""
        evidence = make_evidence_set(
            count=6,
            false_negative=True,
        )
        patterns, _ = pattern_miner.mine_patterns(
            evidence,
            candidate_types=[CandidateType.FALSE_NEGATIVE_PATTERN],
        )
        assert len(patterns) >= 1
        p = patterns[0]
        assert p.candidate_type == CandidateType.FALSE_NEGATIVE_PATTERN


class TestDeterminism:
    """Test that pattern mining is deterministic."""

    def test_same_input_same_output(self, pattern_miner):
        """Same evidence should produce same patterns."""
        evidence = make_evidence_set(count=6)
        patterns1, _ = pattern_miner.mine_patterns(evidence)
        patterns2, _ = pattern_miner.mine_patterns(evidence)

        assert len(patterns1) == len(patterns2)
        for p1, p2 in zip(patterns1, patterns2):
            assert p1.group_key == p2.group_key
            assert p1.support_count == p2.support_count
            assert p1.contradiction_count == p2.contradiction_count
