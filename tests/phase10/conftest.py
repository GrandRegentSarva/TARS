"""
Phase 10 Test Fixtures
=======================
Shared fixtures and builders for Phase 10 learning engine tests.

Builder functions create dicts matching upstream API response structures
so tests don't depend on live Phase 9, Phase 7, Phoenix, Gemini,
Neo4j, PX4, or a simulator.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import pytest

from tars.phase10.evidence_loader import EvidenceLoader
from tars.phase10.models import (
    CandidateKnowledge,
    CandidateResponse,
    CandidateStatus,
    CandidateType,
    EvidenceLevel,
    EvidenceResponse,
    LearningEvidence,
    LearningRunResponse,
    LearningRunStatus,
    RunCandidateAction,
)
from tars.phase10.pattern_miner import PatternMiner
from tars.phase10.scorer import CandidateScorer
from tars.phase10.service import LearningService


# =============================================================================
# Evaluation Builder Helpers
# =============================================================================

def make_evaluation(
    *,
    evaluation_id: Optional[str] = None,
    mission_id: str = "mission_test_001",
    incident_id: str = "inc_test_001",
    reasoning_id: str = "reason_test_001",
    trace_id: Optional[str] = None,
    overall_score: float = 0.85,
    false_positive: bool = False,
    false_negative: bool = False,
    evidence_level: str = "operator_label",
    root_cause_label: str = "correct",
    recommendation_label: str = "correct",
    evaluator_version: str = "v1.0",
) -> dict[str, Any]:
    """Build a Phase 9 evaluation result dict."""
    if evaluation_id is None:
        evaluation_id = f"eval_{uuid.uuid4().hex[:16]}"

    return {
        "evaluation_id": evaluation_id,
        "mission_id": mission_id,
        "incident_id": incident_id,
        "reasoning_id": reasoning_id,
        "trace_id": trace_id,
        "overall_score": overall_score,
        "false_positive": false_positive,
        "false_negative": false_negative,
        "evidence_level": evidence_level,
        "evaluator_version": evaluator_version,
        "created_at": "2026-06-18T10:35:00+00:00",
        "advisory_only": True,
        "metrics": [
            {
                "name": "root_cause_accuracy",
                "score": overall_score,
                "label": root_cause_label,
                "evidence": ["operator_label"],
                "explanation": "Test evaluation.",
            },
            {
                "name": "recommendation_accuracy",
                "score": overall_score,
                "label": recommendation_label,
                "evidence": ["operator_label"],
                "explanation": "Test evaluation.",
            },
        ],
    }


def make_evaluation_set(
    count: int = 10,
    mission_prefix: str = "mission_test",
    incident_family: str = "nav",
    root_cause: str = "gps_interference",
    mitigation: str = "switch_to_visual_odometry",
    outcome: str = "recovered",
    overall_score: float = 0.85,
    root_cause_label: str = "correct",
    recommendation_label: str = "correct",
    false_positive: bool = False,
    false_negative: bool = False,
) -> list[dict[str, Any]]:
    """Build a set of evaluations for pattern mining tests."""
    evals = []
    for i in range(count):
        mission_id = f"{mission_prefix}_{i:03d}"
        evals.append(
            make_evaluation(
                mission_id=mission_id,
                incident_id=f"{incident_family}_inc_{i:03d}",
                reasoning_id=f"reason_{i:03d}",
                overall_score=overall_score,
                root_cause_label=root_cause_label,
                recommendation_label=recommendation_label,
                false_positive=false_positive,
                false_negative=false_negative,
            )
        )
    return evals


def make_evidence(
    *,
    evidence_id: Optional[str] = None,
    mission_id: str = "mission_test_001",
    incident_id: str = "inc_test_001",
    reasoning_id: str = "reason_test_001",
    evaluation_id: str = "eval_test_001",
    trace_id: Optional[str] = None,
    root_cause: str = "gps_interference",
    mitigation: str = "switch_to_visual_odometry",
    outcome: str = "recovered",
    overall_score: float = 0.85,
    root_cause_label: str = "correct",
    recommendation_label: str = "correct",
    false_positive: bool = False,
    false_negative: bool = False,
) -> LearningEvidence:
    """Build a LearningEvidence record."""
    if evidence_id is None:
        evidence_id = f"ev_{uuid.uuid4().hex[:16]}"

    metric_labels = {
        "root_cause_accuracy": root_cause_label,
        "recommendation_accuracy": recommendation_label,
    }
    if false_positive:
        metric_labels["false_positive"] = "true"
    if false_negative:
        metric_labels["false_negative"] = "true"

    return LearningEvidence(
        evidence_id=evidence_id,
        mission_id=mission_id,
        incident_id=incident_id,
        reasoning_id=reasoning_id,
        evaluation_id=evaluation_id,
        trace_id=trace_id,
        root_cause=root_cause,
        mitigation=mitigation,
        outcome=outcome,
        overall_score=overall_score,
        metric_labels=metric_labels,
        evidence_levels=[
            EvidenceLevel.OPERATOR_LABEL.value,
            EvidenceLevel.EVALUATION_METRIC.value,
        ],
    )


def make_evidence_set(
    count: int = 10,
    mission_prefix: str = "mission_test",
    incident_family: str = "nav",
    root_cause: str = "gps_interference",
    mitigation: str = "switch_to_visual_odometry",
    outcome: str = "recovered",
    overall_score: float = 0.85,
    root_cause_label: str = "correct",
    recommendation_label: str = "correct",
    false_positive: bool = False,
    false_negative: bool = False,
) -> list[LearningEvidence]:
    """Build a set of evidence items for pattern mining tests."""
    items = []
    for i in range(count):
        mission_id = f"{mission_prefix}_{i:03d}"
        items.append(
            make_evidence(
                mission_id=mission_id,
                incident_id=f"{incident_family}_inc_{i:03d}",
                reasoning_id=f"reason_{i:03d}",
                evaluation_id=f"eval_{i:03d}",
                root_cause=root_cause,
                mitigation=mitigation,
                outcome=outcome,
                overall_score=overall_score,
                root_cause_label=root_cause_label,
                recommendation_label=recommendation_label,
                false_positive=false_positive,
                false_negative=false_negative,
            )
        )
    return items


# =============================================================================
# Fake Clients
# =============================================================================

class FakePhase9Client:
    """Fake Phase 9 client for testing."""

    def __init__(
        self,
        evaluations: Optional[dict[str, list[dict]]] = None,
        unavailable: bool = False,
    ):
        self._evaluations = evaluations or {}
        self._unavailable = unavailable

    async def get_evaluations_by_mission(
        self, mission_id: str
    ) -> list[dict[str, Any]]:
        if self._unavailable:
            raise ConnectionError("Phase 9 unavailable")
        return self._evaluations.get(mission_id, [])

    async def get_evaluation(
        self, evaluation_id: str
    ) -> Optional[dict[str, Any]]:
        if self._unavailable:
            return None
        for evals in self._evaluations.values():
            for ev in evals:
                if ev.get("evaluation_id") == evaluation_id:
                    return ev
        return None

    async def list_all_evaluations(
        self,
        mission_ids: Optional[list[str]] = None,
        since: Optional[str] = None,
        until: Optional[str] = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        if self._unavailable:
            raise ConnectionError("Phase 9 unavailable")
        all_evals: list[dict[str, Any]] = []
        if mission_ids:
            for mid in mission_ids:
                all_evals.extend(self._evaluations.get(mid, []))
        else:
            for evals in self._evaluations.values():
                all_evals.extend(evals)
        return all_evals[:limit]

    async def health_check(self) -> bool:
        return not self._unavailable


class FakePhase7Client:
    """Fake Phase 7 client for testing."""

    def __init__(
        self,
        incident_memory: Optional[dict[str, dict]] = None,
        mission_outcomes: Optional[dict[str, dict]] = None,
        unavailable: bool = False,
    ):
        self._incident_memory = incident_memory or {}
        self._mission_outcomes = mission_outcomes or {}
        self._unavailable = unavailable

    async def get_incident_memory(
        self, incident_id: str
    ) -> Optional[dict[str, Any]]:
        if self._unavailable:
            return None
        return self._incident_memory.get(incident_id)

    async def get_mission_outcomes(
        self, mission_id: str
    ) -> Optional[dict[str, Any]]:
        if self._unavailable:
            return None
        return self._mission_outcomes.get(mission_id)

    async def get_similar_incidents(
        self, incident_type: str, limit: int = 20
    ) -> list[dict[str, Any]]:
        if self._unavailable:
            return []
        return []

    async def health_check(self) -> bool:
        return not self._unavailable


class FakePhoenixClient:
    """Fake Phoenix client for testing."""

    def __init__(self, enabled: bool = False, unavailable: bool = False):
        self._enabled = enabled
        self._unavailable = unavailable

    @property
    def is_enabled(self) -> bool:
        return self._enabled

    async def get_trace_metadata(
        self, trace_id: str
    ) -> Optional[dict[str, Any]]:
        if not self._enabled or self._unavailable:
            return None
        return {"trace_id": trace_id, "status": "ok"}

    async def get_trace_ids_for_mission(
        self, mission_id: str, limit: int = 50
    ) -> list[str]:
        if not self._enabled or self._unavailable:
            return []
        return []

    async def health_check(self) -> bool:
        return self._enabled and not self._unavailable


class FakeRepository:
    """In-memory fake repository for testing."""

    def __init__(self):
        self._runs: dict[str, dict] = {}
        self._candidates: dict[str, CandidateKnowledge] = {}
        self._evidence: dict[str, list[LearningEvidence]] = {}
        self._run_candidates: dict[str, list[tuple[str, str]]] = {}

    async def create_run(
        self, run_id, filters, learning_version, dry_run=False
    ):
        self._runs[run_id] = {
            "run_id": run_id,
            "status": "running",
            "filters": filters,
            "learning_version": learning_version,
            "dry_run": dry_run,
        }
        return LearningRunResponse(
            run_id=run_id,
            status=LearningRunStatus.RUNNING,
            filters=filters,
            learning_version=learning_version,
            dry_run=dry_run,
        )

    async def complete_run(
        self, run_id, evaluated_cases_read, evidence_items_used,
        candidates_proposed, candidates_updated, candidates_suppressed,
        candidate_ids, warnings
    ):
        if run_id in self._runs:
            self._runs[run_id]["status"] = "complete"

    async def fail_run(
        self, run_id, error_code, error_message, warnings=None
    ):
        if run_id in self._runs:
            self._runs[run_id]["status"] = "failed"

    async def get_run(self, run_id):
        run = self._runs.get(run_id)
        if run is None:
            return None
        return LearningRunResponse(
            run_id=run["run_id"],
            status=LearningRunStatus(run["status"]),
            filters=run.get("filters", {}),
            learning_version=run.get("learning_version", ""),
            dry_run=run.get("dry_run", False),
        )

    async def find_active_candidate_by_dedupe_key(
        self, dedupe_key, learning_version
    ):
        for c in self._candidates.values():
            if (
                c.dedupe_key == dedupe_key
                and c.learning_version == learning_version
                and c.status == CandidateStatus.PROPOSED
            ):
                return CandidateResponse(
                    candidate_id=c.candidate_id,
                    candidate_type=c.candidate_type,
                    status=c.status,
                    statement=c.statement,
                    dedupe_key=c.dedupe_key,
                    learning_version=c.learning_version,
                    advisory_only=True,
                )
        return None

    async def upsert_candidate(self, candidate, evidence_items):
        existing = await self.find_active_candidate_by_dedupe_key(
            candidate.dedupe_key, candidate.learning_version
        )
        is_new = existing is None
        if existing:
            old = self._candidates.get(existing.candidate_id)
            if old:
                old.status = CandidateStatus.SUPERSEDED
        self._candidates[candidate.candidate_id] = candidate
        self._evidence[candidate.candidate_id] = evidence_items
        return candidate.candidate_id, is_new

    async def link_candidate_to_run(self, run_id, candidate_id, action):
        if run_id not in self._run_candidates:
            self._run_candidates[run_id] = []
        self._run_candidates[run_id].append((candidate_id, action.value))

    async def get_candidate(self, candidate_id):
        c = self._candidates.get(candidate_id)
        if c is None:
            return None
        return CandidateResponse(
            candidate_id=c.candidate_id,
            candidate_type=c.candidate_type,
            status=c.status,
            statement=c.statement,
            incident_family=c.incident_family,
            root_cause=c.root_cause,
            mitigation=c.mitigation,
            outcome_family=c.outcome_family,
            support_count=c.support_count,
            contradiction_count=c.contradiction_count,
            distinct_mission_count=c.distinct_mission_count,
            success_rate=c.success_rate,
            mean_overall_score=c.mean_overall_score,
            confidence=c.confidence,
            evidence_ids=c.evidence_ids,
            source_evaluation_ids=c.source_evaluation_ids,
            source_trace_ids=c.source_trace_ids,
            learning_version=c.learning_version,
            dedupe_key=c.dedupe_key,
            advisory_only=True,
            created_at=c.created_at,
        )

    async def list_candidates(
        self, candidate_type=None, status=None, incident_family=None,
        root_cause=None, min_confidence=None, page=1, page_size=50
    ):
        results = []
        for c in self._candidates.values():
            if candidate_type and c.candidate_type.value != candidate_type:
                continue
            if status and c.status.value != status:
                continue
            if incident_family and c.incident_family != incident_family:
                continue
            if root_cause and c.root_cause != root_cause:
                continue
            if min_confidence is not None and c.confidence < min_confidence:
                continue
            results.append(
                CandidateResponse(
                    candidate_id=c.candidate_id,
                    candidate_type=c.candidate_type,
                    status=c.status,
                    statement=c.statement,
                    confidence=c.confidence,
                    dedupe_key=c.dedupe_key,
                    learning_version=c.learning_version,
                    advisory_only=True,
                )
            )
        total = len(results)
        start = (page - 1) * page_size
        return results[start:start + page_size], total

    async def get_evidence(self, candidate_id, page=1, page_size=50):
        items = self._evidence.get(candidate_id, [])
        total = len(items)
        start = (page - 1) * page_size
        page_items = items[start:start + page_size]
        responses = [
            EvidenceResponse(
                evidence_id=e.evidence_id,
                candidate_id=candidate_id,
                mission_id=e.mission_id,
                incident_id=e.incident_id,
                reasoning_id=e.reasoning_id,
                evaluation_id=e.evaluation_id,
                trace_id=e.trace_id,
                root_cause=e.root_cause,
                mitigation=e.mitigation,
                outcome=e.outcome,
                overall_score=e.overall_score,
                metric_labels=e.metric_labels,
                evidence_levels=e.evidence_levels,
            )
            for e in page_items
        ]
        return responses, total

    async def retire_candidate(self, candidate_id, reason):
        c = self._candidates.get(candidate_id)
        if c is None or c.status != CandidateStatus.PROPOSED:
            return False
        c.status = CandidateStatus.RETIRED
        return True


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def fake_phase9():
    """Create a fake Phase 9 client with default evaluations."""
    evals = {}
    for i in range(10):
        mid = f"mission_test_{i:03d}"
        evals[mid] = [
            make_evaluation(
                mission_id=mid,
                incident_id=f"nav_inc_{i:03d}",
                reasoning_id=f"reason_{i:03d}",
            )
        ]
    return FakePhase9Client(evaluations=evals)


@pytest.fixture
def fake_phase9_unavailable():
    """Create a fake Phase 9 client that is unavailable."""
    return FakePhase9Client(unavailable=True)


@pytest.fixture
def fake_phase7():
    """Create a fake Phase 7 client with incident memory."""
    memory = {}
    for i in range(10):
        inc_id = f"nav_inc_{i:03d}"
        memory[inc_id] = {
            "incident_id": inc_id,
            "root_cause": "gps_interference",
            "mitigation": "switch_to_visual_odometry",
            "outcome": "recovered",
        }
    return FakePhase7Client(incident_memory=memory)


@pytest.fixture
def fake_phase7_unavailable():
    """Create a fake Phase 7 client that is unavailable."""
    return FakePhase7Client(unavailable=True)


@pytest.fixture
def fake_phoenix():
    """Create a fake Phoenix client (disabled)."""
    return FakePhoenixClient(enabled=False)


@pytest.fixture
def fake_repository():
    """Create an in-memory fake repository."""
    return FakeRepository()


@pytest.fixture
def evidence_loader(fake_phase9, fake_phase7, fake_phoenix):
    """Create an EvidenceLoader with fake dependencies."""
    return EvidenceLoader(
        phase9_client=fake_phase9,
        phase7_client=fake_phase7,
        phoenix_client=fake_phoenix,
    )


@pytest.fixture
def pattern_miner():
    """Create a PatternMiner with default settings."""
    return PatternMiner(
        min_evaluated_cases=3,
        min_distinct_missions=2,
        min_success_rate=0.70,
        max_false_positive_rate=0.20,
    )


@pytest.fixture
def scorer():
    """Create a CandidateScorer."""
    return CandidateScorer(version="phase10.v1-test")


@pytest.fixture
def learning_service(fake_repository, evidence_loader, pattern_miner, scorer):
    """Create a LearningService with fake dependencies."""
    return LearningService(
        repository=fake_repository,
        evidence_loader=evidence_loader,
        pattern_miner=pattern_miner,
        scorer=scorer,
    )
