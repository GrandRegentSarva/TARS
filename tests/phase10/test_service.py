"""
Phase 10 Service Tests
========================
Tests for end-to-end learning orchestration with fakes and dry-run behavior.
"""

from __future__ import annotations

import pytest

from tars.phase10.evidence_loader import EvidenceLoader
from tars.phase10.models import (
    CandidateType,
    LearningRunRequest,
    LearningRunStatus,
)
from tars.phase10.pattern_miner import PatternMiner
from tars.phase10.scorer import CandidateScorer
from tars.phase10.service import LearningService

from .conftest import (
    FakePhase7Client,
    FakePhase9Client,
    FakePhoenixClient,
    FakeRepository,
    make_evaluation,
)


def _build_service(
    *,
    phase9: FakePhase9Client,
    phase7: FakePhase7Client = None,
    phoenix: FakePhoenixClient = None,
    repository: FakeRepository = None,
) -> LearningService:
    """Build a LearningService with specified fakes."""
    repo = repository or FakeRepository()
    loader = EvidenceLoader(
        phase9_client=phase9,
        phase7_client=phase7 or FakePhase7Client(),
        phoenix_client=phoenix or FakePhoenixClient(),
    )
    return LearningService(
        repository=repo,
        evidence_loader=loader,
        pattern_miner=PatternMiner(
            min_evaluated_cases=3,
            min_distinct_missions=2,
        ),
        scorer=CandidateScorer(version="phase10.v1-test"),
    )


class TestLearningRun:
    """Test learning run orchestration."""

    @pytest.mark.asyncio
    async def test_successful_run(self):
        """A run with sufficient evidence should produce candidates."""
        evals = {}
        phase7_memory = {}
        for i in range(10):
            mid = f"mission_{i:03d}"
            inc_id = f"nav_inc_{i:03d}"
            evals[mid] = [
                make_evaluation(
                    mission_id=mid,
                    incident_id=inc_id,
                )
            ]
            phase7_memory[inc_id] = {
                "root_cause": "gps_interference",
                "mitigation": "switch_to_visual_odometry",
                "outcome": "recovered",
            }

        phase9 = FakePhase9Client(evaluations=evals)
        phase7 = FakePhase7Client(incident_memory=phase7_memory)
        service = _build_service(phase9=phase9, phase7=phase7)

        request = LearningRunRequest(
            mission_ids=list(evals.keys()),
            candidate_types=[CandidateType.MITIGATION_EFFECTIVENESS],
        )
        result = await service.run_learning(request)

        assert result.status == LearningRunStatus.COMPLETE
        assert result.evaluated_cases_read > 0

    @pytest.mark.asyncio
    async def test_dry_run_no_persistence(self):
        """Dry run should not persist candidates."""
        evals = {}
        phase7_memory = {}
        for i in range(10):
            mid = f"mission_dry_{i:03d}"
            inc_id = f"nav_inc_dry_{i:03d}"
            evals[mid] = [
                make_evaluation(mission_id=mid, incident_id=inc_id)
            ]
            phase7_memory[inc_id] = {
                "root_cause": "gps_interference",
                "mitigation": "switch_to_visual_odometry",
                "outcome": "recovered",
            }

        phase9 = FakePhase9Client(evaluations=evals)
        phase7 = FakePhase7Client(incident_memory=phase7_memory)
        repo = FakeRepository()
        service = _build_service(
            phase9=phase9, phase7=phase7, repository=repo
        )

        request = LearningRunRequest(
            mission_ids=list(evals.keys()),
            dry_run=True,
        )
        result = await service.run_learning(request)

        assert result.status == LearningRunStatus.COMPLETE
        assert result.dry_run is True
        # No candidates should be persisted in dry run
        candidates, total = await repo.list_candidates()
        assert total == 0

    @pytest.mark.asyncio
    async def test_empty_evidence_run(self):
        """Run with no evidence should complete with warnings."""
        phase9 = FakePhase9Client(evaluations={})
        service = _build_service(phase9=phase9)

        request = LearningRunRequest(
            mission_ids=["nonexistent_mission"],
        )
        result = await service.run_learning(request)

        assert result.status == LearningRunStatus.COMPLETE
        assert result.evaluated_cases_read == 0
        assert result.candidates_proposed == 0
        assert len(result.warnings) > 0

    @pytest.mark.asyncio
    async def test_phase9_unavailable_fails(self):
        """Phase 9 unavailability should fail the run."""
        phase9 = FakePhase9Client(unavailable=True)
        service = _build_service(phase9=phase9)

        request = LearningRunRequest(
            mission_ids=["mission_001"],
        )
        result = await service.run_learning(request)

        assert result.status == LearningRunStatus.FAILED
        assert result.error_code is not None

    @pytest.mark.asyncio
    async def test_phase7_unavailable_degrades(self):
        """Phase 7 unavailability should degrade, not crash."""
        evals = {}
        for i in range(10):
            mid = f"mission_nop7_{i:03d}"
            evals[mid] = [make_evaluation(mission_id=mid)]

        phase9 = FakePhase9Client(evaluations=evals)
        phase7 = FakePhase7Client(unavailable=True)
        service = _build_service(phase9=phase9, phase7=phase7)

        request = LearningRunRequest(
            mission_ids=list(evals.keys()),
        )
        result = await service.run_learning(request)

        # Should complete, possibly with warnings
        assert result.status == LearningRunStatus.COMPLETE

    @pytest.mark.asyncio
    async def test_run_with_filters(self):
        """Run with filters should apply them."""
        evals = {}
        for i in range(5):
            mid = f"mission_filter_{i:03d}"
            evals[mid] = [make_evaluation(mission_id=mid)]

        phase9 = FakePhase9Client(evaluations=evals)
        service = _build_service(phase9=phase9)

        request = LearningRunRequest(
            mission_ids=list(evals.keys()),
            incident_family="navigation_instability",
            root_cause="gps_interference",
        )
        result = await service.run_learning(request)

        assert result.status == LearningRunStatus.COMPLETE
        assert "incident_family" in result.filters


class TestServiceNonGoals:
    """Test that the service respects non-goals."""

    @pytest.mark.asyncio
    async def test_no_gemini_import(self):
        """Phase 10 must not import Phase 5 provider or invoke Gemini."""
        import importlib
        phase10_service = importlib.import_module("tars.phase10.service")
        source = open(phase10_service.__file__).read()
        assert "gemini" not in source.lower()
        assert "provider" not in source.lower()

    @pytest.mark.asyncio
    async def test_no_flight_control_import(self):
        """Phase 10 must not import flight-control packages."""
        import importlib
        phase10_service = importlib.import_module("tars.phase10.service")
        source = open(phase10_service.__file__).read()
        assert "mavsdk" not in source.lower()
        assert "px4" not in source.lower()

    @pytest.mark.asyncio
    async def test_candidates_always_advisory(self):
        """All candidates must have advisory_only=True."""
        evals = {}
        phase7_memory = {}
        for i in range(10):
            mid = f"mission_adv_{i:03d}"
            inc_id = f"nav_inc_adv_{i:03d}"
            evals[mid] = [
                make_evaluation(mission_id=mid, incident_id=inc_id)
            ]
            phase7_memory[inc_id] = {
                "root_cause": "gps_interference",
                "mitigation": "switch_to_visual_odometry",
                "outcome": "recovered",
            }

        phase9 = FakePhase9Client(evaluations=evals)
        phase7 = FakePhase7Client(incident_memory=phase7_memory)
        repo = FakeRepository()
        service = _build_service(
            phase9=phase9, phase7=phase7, repository=repo
        )

        request = LearningRunRequest(
            mission_ids=list(evals.keys()),
        )
        await service.run_learning(request)

        candidates, _ = await repo.list_candidates()
        for c in candidates:
            assert c.advisory_only is True
