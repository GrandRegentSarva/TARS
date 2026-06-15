"""
Phase 7 Test Fixtures
=====================
Shared fixtures and builders for Phase 7 operational memory tests.

Builder functions create dicts matching upstream API response structures
so tests don't depend on live Phase 2, Phase 4, or Phase 5 services.

Neo4j integration tests use a separate test database and skip if
Neo4j is unavailable.
"""

from __future__ import annotations

import socket
from datetime import datetime, timezone
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio

from tars.phase7.phase2_client import Phase2Client
from tars.phase7.phase4_client import Phase4Client
from tars.phase7.phase5_client import Phase5Client
from tars.phase7.service import MemoryService


# =============================================================================
# Mission Builder Helpers
# =============================================================================

def make_mission(
    *,
    mission_id: str = "mission_test_001",
    drone_id: str = "tars-sim-01",
    start_time: str = "2026-06-15T10:00:00+00:00",
    end_time: Optional[str] = "2026-06-15T10:30:00+00:00",
    mission_result: str = "success",
    summary: Optional[dict[str, Any]] = None,
    source_file: Optional[str] = None,
    created_at: str = "2026-06-15T10:30:05+00:00",
) -> dict[str, Any]:
    """Build a Phase 2 mission detail dict."""
    return {
        "mission_id": mission_id,
        "drone_id": drone_id,
        "start_time": start_time,
        "end_time": end_time,
        "mission_result": mission_result,
        "summary": summary,
        "source_file": source_file,
        "created_at": created_at,
        "faults": [],
    }


def make_failed_mission(
    mission_id: str = "mission_test_002",
) -> dict[str, Any]:
    """Build a failed mission detail dict."""
    return make_mission(
        mission_id=mission_id,
        mission_result="failed",
        end_time="2026-06-15T10:15:00+00:00",
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
    start_sequence: int = 5,
    end_sequence: int = 10,
    start_ms: int = 5000,
    end_ms: int = 10000,
    contributing_states: int = 6,
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
        "start_sequence": start_sequence,
        "end_sequence": end_sequence,
        "start_ms": start_ms,
        "end_ms": end_ms,
        "contributing_states": contributing_states,
        "peak_risk": peak_risk,
        "phases": phases or ["cruise"],
        "evidence": evidence or [
            "GPS quality degraded during flight",
            "Attitude unstable while cruising",
        ],
    }


def make_battery_incident(
    incident_id: str = "inc_battery_001",
    mission_id: str = "mission_test_001",
) -> dict[str, Any]:
    """Build a battery degradation incident."""
    return make_incident(
        incident_id=incident_id,
        mission_id=mission_id,
        incident_type="battery_degradation",
        severity="medium",
        peak_risk=0.55,
        evidence=[
            "Battery level dropping faster than expected",
            "Battery voltage below nominal threshold",
        ],
    )


def make_nav_incident_2(
    incident_id: str = "inc_nav_002",
    mission_id: str = "mission_test_002",
) -> dict[str, Any]:
    """Build a second navigation instability incident for similarity testing."""
    return make_incident(
        incident_id=incident_id,
        mission_id=mission_id,
        incident_type="navigation_instability",
        severity="high",
        peak_risk=0.82,
        start_ms=3000,
        end_ms=8000,
        evidence=[
            "GPS signal lost during cruise",
            "Position estimate diverged",
        ],
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
    root_cause: str = "GPS interference from nearby structures",
    confidence: float = 0.85,
    recommendation: str = "Consider switching to visual odometry when GPS quality degrades",
    rationale: str = "GPS signal showed degradation pattern consistent with multipath interference",
    contributing_factors: Optional[list[str]] = None,
    uncertainties: Optional[list[str]] = None,
    model: str = "gemini-2.5-flash",
    prompt_version: str = "v1.0",
    created_at: str = "2026-06-15T10:35:00+00:00",
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


def make_reasoning_2(
    incident_id: str = "inc_nav_002",
    mission_id: str = "mission_test_002",
) -> dict[str, Any]:
    """Build a second reasoning result for similarity testing."""
    return make_reasoning(
        reasoning_id="reason_test_002",
        mission_id=mission_id,
        incident_id=incident_id,
        root_cause="GPS interference from nearby structures",
        confidence=0.91,
        recommendation="Switch navigation source to visual odometry",
        rationale="GPS signal completely lost, consistent with RF interference",
        model="gemini-2.5-flash",
        prompt_version="v1.0",
    )


# =============================================================================
# Fake Client Fixtures
# =============================================================================

class FakePhase2Client:
    """Fake Phase 2 client for testing."""

    def __init__(self, missions: Optional[dict[str, dict]] = None):
        self._missions = missions or {}

    async def get_mission(self, mission_id: str) -> dict[str, Any]:
        if mission_id not in self._missions:
            from tars.phase7.phase2_client import Phase2NotFoundError
            raise Phase2NotFoundError(f"Mission '{mission_id}' not found")
        return self._missions[mission_id]

    async def health_check(self) -> bool:
        return True


class FakePhase4Client:
    """Fake Phase 4 client for testing."""

    def __init__(self, incidents: Optional[dict[str, list[dict]]] = None):
        self._incidents = incidents or {}

    async def get_incidents(self, mission_id: str) -> list[dict[str, Any]]:
        return self._incidents.get(mission_id, [])

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

    async def get_analyses(self, mission_id: str) -> list[dict[str, Any]]:
        if self._unavailable:
            from tars.phase7.phase5_client import Phase5UnavailableError
            raise Phase5UnavailableError("Phase 5 unavailable (fake)")
        return self._analyses.get(mission_id, [])

    async def health_check(self) -> bool:
        return not self._unavailable


@pytest.fixture
def fake_phase2():
    """Create a fake Phase 2 client with default test mission."""
    return FakePhase2Client(missions={
        "mission_test_001": make_mission(),
        "mission_test_002": make_failed_mission(),
    })


@pytest.fixture
def fake_phase4():
    """Create a fake Phase 4 client with default test incidents."""
    return FakePhase4Client(incidents={
        "mission_test_001": [make_incident()],
        "mission_test_002": [make_nav_incident_2()],
    })


@pytest.fixture
def fake_phase5():
    """Create a fake Phase 5 client with default test reasoning."""
    return FakePhase5Client(analyses={
        "mission_test_001": [make_reasoning()],
        "mission_test_002": [make_reasoning_2()],
    })


@pytest.fixture
def fake_phase5_unavailable():
    """Create a fake Phase 5 client that is unavailable."""
    return FakePhase5Client(unavailable=True)


@pytest.fixture
def memory_service(fake_phase2, fake_phase4, fake_phase5):
    """Create a MemoryService with fake clients."""
    return MemoryService(
        phase2_client=fake_phase2,
        phase4_client=fake_phase4,
        phase5_client=fake_phase5,
    )


@pytest.fixture
def memory_service_no_reasoning(fake_phase2, fake_phase4, fake_phase5_unavailable):
    """Create a MemoryService with unavailable Phase 5."""
    return MemoryService(
        phase2_client=fake_phase2,
        phase4_client=fake_phase4,
        phase5_client=fake_phase5_unavailable,
    )


# =============================================================================
# Neo4j Test Helpers
# =============================================================================

def _neo4j_is_reachable(host: str = "localhost", port: int = 7687) -> bool:
    """Check if Neo4j is reachable via TCP."""
    try:
        with socket.create_connection((host, port), timeout=2.0):
            return True
    except OSError:
        return False


requires_neo4j = pytest.mark.skipif(
    not _neo4j_is_reachable(),
    reason="Neo4j not available on localhost:7687",
)
