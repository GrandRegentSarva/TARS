"""
Phase 9 Test Fixtures
=====================
Shared fixtures and builders for Phase 9 evaluation layer tests.

Builder functions create dicts matching upstream API response structures
so tests don't depend on live Phase 4, Phase 5, Phase 7, Phoenix,
Gemini, Neo4j, or PX4 services.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest

from tars.phase9.evaluator import Evaluator
from tars.phase9.ground_truth import GroundTruthLoader, GroundTruthResult
from tars.phase9.models import (
    ClassificationLabel,
    EvaluationMetric,
    EvaluationResult,
    EvidenceLevel,
    GroundTruthLabel,
    GroundTruthPayload,
    GroundTruthSource,
    MetricName,
)


# =============================================================================
# Reasoning Builder Helpers
# =============================================================================

def make_reasoning(
    *,
    reasoning_id: str = "reason_test_001",
    mission_id: str = "mission_test_001",
    incident_id: str = "inc_test_001",
    incident_type: str = "navigation_instability",
    root_cause: str = "gps_interference",
    confidence: float = 0.85,
    recommendation: str = "Consider switching to visual odometry when GPS quality degrades",
    rationale: str = "GPS signal showed degradation pattern consistent with multipath interference",
    contributing_factors: Optional[list[str]] = None,
    uncertainties: Optional[list[str]] = None,
    model: str = "gemini-2.5-flash",
    prompt_version: str = "v1.0",
    created_at: str = "2026-06-18T10:35:00+00:00",
    advisory_only: bool = True,
) -> dict[str, Any]:
    """Build a Phase 5 reasoning result dict."""
    return {
        "reasoning_id": reasoning_id,
        "mission_id": mission_id,
        "incident_id": incident_id,
        "incident_type": incident_type,
        "root_cause": root_cause,
        "confidence": confidence,
        "recommendation": recommendation,
        "rationale": rationale,
        "contributing_factors": contributing_factors or [
            "Urban environment with tall buildings",
        ],
        "uncertainties": uncertainties or [
            "Exact interference source unknown",
        ],
        "model": model,
        "prompt_version": prompt_version,
        "created_at": created_at,
        "advisory_only": advisory_only,
    }


def make_reasoning_wrong_cause() -> dict[str, Any]:
    """Build a reasoning result with wrong root cause."""
    return make_reasoning(
        reasoning_id="reason_wrong_001",
        root_cause="battery_degradation",
        recommendation="Monitor battery levels closely",
        rationale="Battery showed voltage drops",
    )


def make_reasoning_partial_cause() -> dict[str, Any]:
    """Build a reasoning result with partially correct root cause."""
    return make_reasoning(
        reasoning_id="reason_partial_001",
        root_cause="navigation_instability",
        recommendation="Consider switching to visual odometry",
        rationale="Navigation showed instability",
    )


def make_reasoning_with_control_command() -> dict[str, Any]:
    """Build a reasoning result with a control command in recommendation."""
    return make_reasoning(
        reasoning_id="reason_control_001",
        recommendation="Execute RTL immediately and land the drone",
    )


# =============================================================================
# Incident Builder Helpers
# =============================================================================

def make_incident(
    *,
    incident_id: str = "inc_test_001",
    mission_id: str = "mission_test_001",
    incident_type: str = "navigation_instability",
    severity: str = "high",
    start_ms: int = 5000,
    end_ms: int = 10000,
    peak_risk: float = 0.78,
    phases: Optional[list[str]] = None,
    evidence: Optional[list[str]] = None,
) -> dict[str, Any]:
    """Build a Phase 4 incident dict."""
    return {
        "incident_id": incident_id,
        "mission_id": mission_id,
        "incident_type": incident_type,
        "severity": severity,
        "start_ms": start_ms,
        "end_ms": end_ms,
        "peak_risk": peak_risk,
        "phases": phases or ["cruise"],
        "evidence": evidence or [
            "GPS quality degraded during flight",
            "Attitude unstable while cruising",
        ],
    }


# =============================================================================
# Ground Truth Helpers
# =============================================================================

def make_ground_truth(
    *,
    root_cause: str = "gps_interference",
    preferred_mitigation: str = "switch_to_visual_odometry",
    outcome: str = "recovered",
    source: GroundTruthSource = GroundTruthSource.OPERATOR_LABEL,
) -> GroundTruthResult:
    """Build a GroundTruthResult with evidence."""
    label = GroundTruthLabel(
        root_cause=root_cause,
        preferred_mitigation=preferred_mitigation,
        outcome=outcome,
        source=source,
        labeled_by="test",
    )
    return GroundTruthResult(
        label=label,
        evidence_level=EvidenceLevel.OPERATOR_LABEL.value,
        has_evidence=True,
    )


def make_ground_truth_no_evidence() -> GroundTruthResult:
    """Build a GroundTruthResult with no evidence."""
    return GroundTruthResult.insufficient()


def make_ground_truth_nominal() -> GroundTruthResult:
    """Build a GroundTruthResult indicating nominal outcome."""
    label = GroundTruthLabel(
        root_cause="operator_abort",
        preferred_mitigation=None,
        outcome="nominal",
        source=GroundTruthSource.OPERATOR_LABEL,
        labeled_by="test",
    )
    return GroundTruthResult(
        label=label,
        evidence_level=EvidenceLevel.OPERATOR_LABEL.value,
        has_evidence=True,
    )


def make_ground_truth_failed() -> GroundTruthResult:
    """Build a GroundTruthResult indicating failed outcome."""
    label = GroundTruthLabel(
        root_cause="battery_failure",
        preferred_mitigation="return_to_launch",
        outcome="failed",
        source=GroundTruthSource.OPERATOR_LABEL,
        labeled_by="test",
    )
    return GroundTruthResult(
        label=label,
        evidence_level=EvidenceLevel.OPERATOR_LABEL.value,
        has_evidence=True,
    )


# =============================================================================
# Fake Clients
# =============================================================================

class FakePhase4Client:
    """Fake Phase 4 client for testing."""

    def __init__(self, incidents: Optional[dict[str, list[dict]]] = None):
        self._incidents = incidents or {}

    async def get_incidents(self, mission_id: str) -> list[dict[str, Any]]:
        return self._incidents.get(mission_id, [])

    async def get_incident(
        self, mission_id: str, incident_id: str
    ) -> Optional[dict[str, Any]]:
        for inc in self._incidents.get(mission_id, []):
            if inc.get("incident_id") == incident_id:
                return inc
        return None

    async def health_check(self) -> bool:
        return True


class FakePhase5Client:
    """Fake Phase 5 client for testing."""

    def __init__(
        self,
        analyses: Optional[dict[str, list[dict]]] = None,
        unavailable: bool = False,
    ):
        self._analyses = analyses or {}
        self._unavailable = unavailable

    async def get_reasoning(
        self, mission_id: str, incident_id: str
    ) -> Optional[dict[str, Any]]:
        if self._unavailable:
            return None
        for analysis in self._analyses.get(mission_id, []):
            if analysis.get("incident_id") == incident_id:
                return analysis
        return None

    async def get_reasoning_by_id(
        self, reasoning_id: str, mission_id: str
    ) -> Optional[dict[str, Any]]:
        if self._unavailable:
            return None
        for analysis in self._analyses.get(mission_id, []):
            if analysis.get("reasoning_id") == reasoning_id:
                return analysis
        return None

    async def list_analyses(self, mission_id: str) -> list[dict[str, Any]]:
        if self._unavailable:
            return []
        return self._analyses.get(mission_id, [])

    async def health_check(self) -> bool:
        return not self._unavailable


class FakePhase7Client:
    """Fake Phase 7 client for testing."""

    def __init__(self, unavailable: bool = False):
        self._unavailable = unavailable

    async def get_incident_memory(
        self, incident_id: str
    ) -> Optional[dict[str, Any]]:
        if self._unavailable:
            return None
        return None

    async def get_mission_outcomes(
        self, mission_id: str
    ) -> Optional[dict[str, Any]]:
        if self._unavailable:
            return None
        return None

    async def health_check(self) -> bool:
        return not self._unavailable


class FakeRepository:
    """In-memory fake repository for testing."""

    def __init__(self):
        self._evaluations: dict[str, dict] = {}
        self._labels: list[dict] = []

    async def find_existing_evaluation(
        self, mission_id, incident_id, reasoning_id, evaluator_version
    ):
        key = f"{mission_id}:{incident_id}:{reasoning_id}:{evaluator_version}"
        return self._evaluations.get(key)

    async def save_evaluation(self, result):
        key = (
            f"{result.mission_id}:{result.incident_id}:"
            f"{result.reasoning_id}:{result.evaluator_version}"
        )
        self._evaluations[key] = result
        return result.evaluation_id

    async def overwrite_evaluation(self, result):
        return await self.save_evaluation(result)

    async def get_evaluation(self, evaluation_id):
        for ev in self._evaluations.values():
            if hasattr(ev, "evaluation_id") and ev.evaluation_id == evaluation_id:
                return ev
        return None

    async def get_evaluations_by_mission(self, mission_id):
        return [
            ev for ev in self._evaluations.values()
            if hasattr(ev, "mission_id") and ev.mission_id == mission_id
        ]

    async def get_evaluations_by_reasoning(self, reasoning_id):
        return [
            ev for ev in self._evaluations.values()
            if hasattr(ev, "reasoning_id") and ev.reasoning_id == reasoning_id
        ]

    async def get_similar_evaluations(
        self, incident_type, severity, root_cause_family,
        exclude_evaluation_id=None, limit=20
    ):
        return []

    async def upsert_label(
        self, mission_id, incident_id, root_cause, preferred_mitigation,
        outcome, source, labeled_by, labeled_at
    ):
        from tars.phase9.models import GroundTruthLabelResponse, GroundTruthSource

        now = datetime.now(timezone.utc)
        label_id = f"label_test_{len(self._labels)}"
        response = GroundTruthLabelResponse(
            label_id=label_id,
            mission_id=mission_id,
            incident_id=incident_id,
            root_cause=root_cause,
            preferred_mitigation=preferred_mitigation,
            outcome=outcome,
            source=GroundTruthSource(source),
            labeled_by=labeled_by,
            labeled_at=labeled_at or now,
            created_at=now,
        )
        self._labels.append(response)
        return response

    async def get_labels_for_target(self, mission_id, incident_id=None):
        return [
            label for label in self._labels
            if label.mission_id == mission_id
            and label.incident_id == incident_id
        ]


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def evaluator() -> Evaluator:
    """Create a deterministic evaluator."""
    return Evaluator(version="v1.0-test")


@pytest.fixture
def fake_phase4():
    """Create a fake Phase 4 client with default test incidents."""
    return FakePhase4Client(incidents={
        "mission_test_001": [make_incident()],
    })


@pytest.fixture
def fake_phase5():
    """Create a fake Phase 5 client with default test reasoning."""
    return FakePhase5Client(analyses={
        "mission_test_001": [make_reasoning()],
    })


@pytest.fixture
def fake_phase5_unavailable():
    """Create a fake Phase 5 client that is unavailable."""
    return FakePhase5Client(unavailable=True)


@pytest.fixture
def fake_phase7():
    """Create a fake Phase 7 client."""
    return FakePhase7Client()


@pytest.fixture
def fake_phase7_unavailable():
    """Create a fake Phase 7 client that is unavailable."""
    return FakePhase7Client(unavailable=True)


@pytest.fixture
def fake_repository():
    """Create an in-memory fake repository."""
    return FakeRepository()


@pytest.fixture
def ground_truth_loader(fake_repository, fake_phase7):
    """Create a GroundTruthLoader with fake dependencies."""
    return GroundTruthLoader(
        repository=fake_repository,
        phase7_client=fake_phase7,
    )
