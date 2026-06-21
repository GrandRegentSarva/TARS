"""
Phase 10 Evidence Loader Tests
================================
Tests for evaluation-memory merge, dedupe, missing context,
and bounded evidence.
"""

from __future__ import annotations

import pytest

from tars.phase10.evidence_loader import (
    EvidenceLoader,
    is_negative_outcome,
    is_positive_outcome,
    normalize_string,
)
from tars.phase10.models import EvidenceLevel

from .conftest import (
    FakePhase7Client,
    FakePhase9Client,
    FakePhoenixClient,
    make_evaluation,
)


class TestNormalization:
    """Test string normalization."""

    def test_normalize_basic(self):
        assert normalize_string("GPS Interference") == "gps_interference"

    def test_normalize_dashes(self):
        assert normalize_string("gps-interference") == "gps_interference"

    def test_normalize_none(self):
        assert normalize_string(None) is None

    def test_normalize_whitespace(self):
        assert normalize_string("  hello world  ") == "hello_world"


class TestOutcomeClassification:
    """Test outcome classification helpers."""

    def test_positive_outcomes(self):
        assert is_positive_outcome("recovered") is True
        assert is_positive_outcome("stabilized") is True
        assert is_positive_outcome("mitigated") is True
        assert is_positive_outcome("nominal") is True

    def test_negative_outcomes(self):
        assert is_negative_outcome("failed") is True
        assert is_negative_outcome("crashed") is True
        assert is_negative_outcome("degraded") is True

    def test_none_outcome(self):
        assert is_positive_outcome(None) is False
        assert is_negative_outcome(None) is False

    def test_unknown_outcome(self):
        assert is_positive_outcome("unknown") is False
        assert is_negative_outcome("unknown") is False


class TestEvidenceLoader:
    """Test evidence loading and merging."""

    @pytest.mark.asyncio
    async def test_load_evidence_basic(self, evidence_loader):
        """Load evidence from fake Phase 9 with Phase 7 enrichment."""
        mission_ids = [f"mission_test_{i:03d}" for i in range(5)]
        evidence, warnings = await evidence_loader.load_evidence(
            mission_ids=mission_ids,
            limit=50,
        )
        assert len(evidence) > 0
        # Each evidence should have a mission_id
        for ev in evidence:
            assert ev.mission_id != ""

    @pytest.mark.asyncio
    async def test_load_evidence_deduplication(self):
        """Duplicate evaluations should not double-count evidence."""
        eval_data = make_evaluation(
            evaluation_id="eval_dup_001",
            mission_id="mission_dup",
        )
        phase9 = FakePhase9Client(evaluations={
            "mission_dup": [eval_data, eval_data],  # Duplicate
        })
        loader = EvidenceLoader(
            phase9_client=phase9,
            phase7_client=FakePhase7Client(),
        )
        evidence, warnings = await loader.load_evidence(
            mission_ids=["mission_dup"],
        )
        # Should deduplicate by evaluation_id
        assert len(evidence) == 1

    @pytest.mark.asyncio
    async def test_load_evidence_no_evaluations(self):
        """Empty evaluations should produce a warning."""
        phase9 = FakePhase9Client(evaluations={})
        loader = EvidenceLoader(phase9_client=phase9)
        evidence, warnings = await loader.load_evidence(
            mission_ids=["nonexistent"],
        )
        assert len(evidence) == 0
        assert any("No evaluations" in w for w in warnings)

    @pytest.mark.asyncio
    async def test_load_evidence_phase7_enrichment(self):
        """Phase 7 should enrich evidence with root cause and outcome."""
        eval_data = make_evaluation(mission_id="mission_enrich")
        phase9 = FakePhase9Client(evaluations={
            "mission_enrich": [eval_data],
        })
        phase7 = FakePhase7Client(incident_memory={
            "inc_test_001": {
                "root_cause": "gps_interference",
                "mitigation": "switch_to_visual_odometry",
                "outcome": "recovered",
            },
        })
        loader = EvidenceLoader(
            phase9_client=phase9,
            phase7_client=phase7,
        )
        evidence, warnings = await loader.load_evidence(
            mission_ids=["mission_enrich"],
        )
        assert len(evidence) == 1
        assert evidence[0].root_cause == "gps_interference"
        assert evidence[0].mitigation == "switch_to_visual_odometry"
        assert evidence[0].outcome == "recovered"

    @pytest.mark.asyncio
    async def test_load_evidence_phase7_unavailable(self):
        """Phase 7 unavailability should produce warnings, not crashes."""
        eval_data = make_evaluation(mission_id="mission_no_p7")
        phase9 = FakePhase9Client(evaluations={
            "mission_no_p7": [eval_data],
        })
        phase7 = FakePhase7Client(unavailable=True)
        loader = EvidenceLoader(
            phase9_client=phase9,
            phase7_client=phase7,
        )
        evidence, warnings = await loader.load_evidence(
            mission_ids=["mission_no_p7"],
        )
        # Should still produce evidence, just without Phase 7 enrichment
        assert len(evidence) == 1
        assert evidence[0].root_cause is None

    @pytest.mark.asyncio
    async def test_load_evidence_bounded(self):
        """Evidence loading should respect the limit parameter."""
        evals = {}
        for i in range(20):
            mid = f"mission_bounded_{i:03d}"
            evals[mid] = [make_evaluation(mission_id=mid)]
        phase9 = FakePhase9Client(evaluations=evals)
        loader = EvidenceLoader(phase9_client=phase9)
        evidence, warnings = await loader.load_evidence(
            mission_ids=list(evals.keys()),
            limit=5,
        )
        assert len(evidence) <= 5

    @pytest.mark.asyncio
    async def test_evidence_contains_metric_labels(self):
        """Evidence should contain metric labels from evaluation."""
        eval_data = make_evaluation(
            mission_id="mission_labels",
            root_cause_label="correct",
            recommendation_label="partially_correct",
        )
        phase9 = FakePhase9Client(evaluations={
            "mission_labels": [eval_data],
        })
        loader = EvidenceLoader(phase9_client=phase9)
        evidence, _ = await loader.load_evidence(
            mission_ids=["mission_labels"],
        )
        assert len(evidence) == 1
        assert evidence[0].metric_labels.get("root_cause_accuracy") == "correct"
        assert evidence[0].metric_labels.get("recommendation_accuracy") == "partially_correct"

    @pytest.mark.asyncio
    async def test_evidence_false_positive_flag(self):
        """False positive flag should be in metric labels."""
        eval_data = make_evaluation(
            mission_id="mission_fp",
            false_positive=True,
        )
        phase9 = FakePhase9Client(evaluations={
            "mission_fp": [eval_data],
        })
        loader = EvidenceLoader(phase9_client=phase9)
        evidence, _ = await loader.load_evidence(
            mission_ids=["mission_fp"],
        )
        assert len(evidence) == 1
        assert evidence[0].metric_labels.get("false_positive") == "true"

    @pytest.mark.asyncio
    async def test_no_phase9_client(self):
        """No Phase 9 client should return empty evidence."""
        loader = EvidenceLoader(phase9_client=None)
        evidence, warnings = await loader.load_evidence(
            mission_ids=["mission_none"],
        )
        assert len(evidence) == 0

    @pytest.mark.asyncio
    async def test_phase7_list_form_root_causes(self):
        """Phase 7 real API returns root_causes as a list of dicts."""
        eval_data = make_evaluation(
            mission_id="mission_list",
            incident_id="nav_inc_list",
        )
        phase9 = FakePhase9Client(evaluations={
            "mission_list": [eval_data],
        })
        phase7 = FakePhase7Client(incident_memory={
            "nav_inc_list": {
                "root_causes": [
                    {"classification": "GPS Interference", "root_cause_id": "rc_001"},
                ],
                "applied_mitigations": [
                    {"description": "Switch to Visual Odometry", "mitigation_id": "mit_001"},
                ],
                "outcomes": [
                    {"status": "recovered", "outcome_id": "out_001"},
                ],
            },
        })
        loader = EvidenceLoader(
            phase9_client=phase9,
            phase7_client=phase7,
        )
        evidence, warnings = await loader.load_evidence(
            mission_ids=["mission_list"],
        )
        assert len(evidence) == 1
        assert evidence[0].root_cause == "gps_interference"
        assert evidence[0].mitigation == "switch_to_visual_odometry"
        assert evidence[0].outcome == "recovered"

    @pytest.mark.asyncio
    async def test_incident_family_filter(self):
        """Incident family filter should exclude non-matching evidence."""
        evals = {
            "mission_fam": [
                make_evaluation(
                    mission_id="mission_fam",
                    incident_id="nav_inc_001",
                ),
                make_evaluation(
                    mission_id="mission_fam",
                    incident_id="battery_inc_001",
                ),
            ],
        }
        phase9 = FakePhase9Client(evaluations=evals)
        loader = EvidenceLoader(phase9_client=phase9)
        evidence, _ = await loader.load_evidence(
            mission_ids=["mission_fam"],
            incident_family="nav",
        )
        assert len(evidence) == 1
        assert evidence[0].incident_id == "nav_inc_001"

    @pytest.mark.asyncio
    async def test_no_mission_ids_returns_all(self):
        """When no mission_ids provided, FakePhase9Client returns all."""
        evals = {
            "m1": [make_evaluation(mission_id="m1")],
            "m2": [make_evaluation(mission_id="m2")],
        }
        phase9 = FakePhase9Client(evaluations=evals)
        loader = EvidenceLoader(phase9_client=phase9)
        evidence, _ = await loader.load_evidence()
        assert len(evidence) == 2
