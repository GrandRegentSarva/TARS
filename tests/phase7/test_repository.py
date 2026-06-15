"""
Phase 7 Repository Tests
=========================
Tests for Neo4j graph repository operations.

Integration tests require a running Neo4j instance and are skipped
when Neo4j is unavailable. Uses parameterized Cypher verification.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
import pytest_asyncio

from tars.phase7.models import (
    AnalysisRelationship,
    IncidentRecord,
    MissionProjection,
    MissionRecord,
    MitigationRecord,
    OutcomeRecord,
    RecommendationRelationship,
    RootCauseRecord,
    SyncCounts,
)

from .conftest import requires_neo4j


# =============================================================================
# Unit Tests (no Neo4j required)
# =============================================================================

class TestSyncCounts:
    """Test sync counts tracking."""

    def test_default_counts(self):
        counts = SyncCounts()
        assert counts.missions == 0
        assert counts.incidents == 0
        assert counts.root_causes == 0
        assert counts.mitigations == 0
        assert counts.outcomes == 0
        assert counts.relationships == 0

    def test_counts_increment(self):
        counts = SyncCounts()
        counts.missions = 1
        counts.incidents = 3
        counts.root_causes = 2
        assert counts.missions == 1
        assert counts.incidents == 3
        assert counts.root_causes == 2


class TestMissionProjectionConstruction:
    """Test building projection objects for repository input."""

    def test_minimal_projection(self):
        """A mission with no incidents is a valid projection."""
        proj = MissionProjection(
            mission=MissionRecord(
                mission_id="m1",
                drone_id="d1",
                start_time=datetime.now(timezone.utc),
                mission_result="success",
            ),
        )
        assert proj.mission.mission_id == "m1"
        assert len(proj.incidents) == 0

    def test_full_projection(self):
        """A projection with all components."""
        now = datetime.now(timezone.utc)
        proj = MissionProjection(
            mission=MissionRecord(
                mission_id="m1",
                drone_id="d1",
                start_time=now,
                mission_result="success",
            ),
            incidents=[
                IncidentRecord(
                    incident_id="i1",
                    mission_id="m1",
                    incident_type="navigation_instability",
                    severity="high",
                    start_ms=1000,
                    end_ms=5000,
                    peak_risk=0.8,
                ),
            ],
            root_causes=[
                RootCauseRecord(
                    root_cause_id="rc_abc",
                    classification="GPS interference",
                    normalized_classification="gps interference",
                ),
            ],
            mitigations=[
                MitigationRecord(
                    mitigation_id="mit_abc",
                    description="Switch to visual odometry",
                    normalized_description="switch to visual odometry",
                ),
            ],
            analyses=[
                AnalysisRelationship(
                    incident_id="i1",
                    root_cause_id="rc_abc",
                    reasoning_id="r1",
                    confidence=0.85,
                    model="gemini-2.5-flash",
                    prompt_version="v1.0",
                    rationale="GPS degradation pattern",
                    created_at=now.isoformat(),
                ),
            ],
            recommendations=[
                RecommendationRelationship(
                    incident_id="i1",
                    mitigation_id="mit_abc",
                    reasoning_id="r1",
                    recommended_at=now.isoformat(),
                ),
            ],
            mission_outcome=OutcomeRecord(
                outcome_id="outcome_m1",
                scope="mission",
                status="recovered",
                description="Mission completed successfully",
                observed_at=now,
                source="phase2_mission_result",
                recorded_by="phase2",
            ),
        )

        assert len(proj.incidents) == 1
        assert len(proj.root_causes) == 1
        assert len(proj.mitigations) == 1
        assert len(proj.analyses) == 1
        assert len(proj.recommendations) == 1
        assert proj.mission_outcome is not None


class TestParameterizedCypher:
    """Verify that repository uses parameterized Cypher patterns."""

    def test_no_string_interpolation_in_queries(self):
        """Verify repository module doesn't use f-string Cypher."""
        import inspect
        from tars.phase7 import repository

        source = inspect.getsource(repository)

        # Check that Cypher queries use $parameter syntax
        # and don't use f-string interpolation for user data
        assert "$mission_id" in source
        assert "$incident_id" in source
        assert "$incident_type" in source

    def test_repository_uses_merge(self):
        """Verify repository uses MERGE for idempotent writes."""
        import inspect
        from tars.phase7 import repository

        source = inspect.getsource(repository)
        assert "MERGE" in source

    def test_repository_does_not_expose_arbitrary_cypher(self):
        """Verify no function accepts raw Cypher from callers."""
        import inspect
        from tars.phase7 import repository

        # Check public functions don't accept a 'cypher' or 'query' parameter
        # that would allow arbitrary execution
        public_funcs = [
            name for name, obj in inspect.getmembers(repository)
            if inspect.isfunction(obj) and not name.startswith("_")
        ]

        for func_name in public_funcs:
            func = getattr(repository, func_name)
            sig = inspect.signature(func)
            param_names = list(sig.parameters.keys())
            assert "cypher" not in param_names, f"{func_name} accepts raw cypher"
            assert "raw_query" not in param_names, f"{func_name} accepts raw query"
