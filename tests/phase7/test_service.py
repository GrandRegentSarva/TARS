"""
Phase 7 Service Tests
======================
Tests for the MemoryService orchestration layer.

Uses fake clients and mocked repository to test service logic
without requiring Neo4j or live upstream APIs.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tars.phase7.models import (
    OutcomeStatus,
    SyncCounts,
    SyncStatus,
)
from tars.phase7.service import MemoryService

from .conftest import (
    FakePhase2Client,
    FakePhase4Client,
    FakePhase5Client,
    make_battery_incident,
    make_incident,
    make_mission,
    make_failed_mission,
    make_nav_incident_2,
    make_reasoning,
    make_reasoning_2,
)


# =============================================================================
# Sync Tests
# =============================================================================

class TestSyncMission:
    """Test mission synchronization orchestration."""

    @pytest.mark.asyncio
    @patch("tars.phase7.service.repository")
    async def test_sync_success_with_reasoning(self, mock_repo):
        """Sync a mission with incidents and reasoning."""
        mock_repo.upsert_sync_status = AsyncMock()
        mock_repo.project_mission = AsyncMock(return_value=SyncCounts(
            missions=1, incidents=1, root_causes=1,
            mitigations=1, relationships=2,
        ))

        service = MemoryService(
            phase2_client=FakePhase2Client(missions={
                "m1": make_mission(mission_id="m1"),
            }),
            phase4_client=FakePhase4Client(incidents={
                "m1": [make_incident(mission_id="m1")],
            }),
            phase5_client=FakePhase5Client(analyses={
                "m1": [make_reasoning(mission_id="m1")],
            }),
        )

        result = await service.sync_mission("m1")

        assert result.status == SyncStatus.COMPLETE
        assert result.counts.missions == 1
        assert result.counts.incidents == 1
        assert result.counts.root_causes == 1
        mock_repo.project_mission.assert_called_once()

    @pytest.mark.asyncio
    @patch("tars.phase7.service.repository")
    async def test_sync_without_reasoning(self, mock_repo):
        """Sync a mission without requesting reasoning."""
        mock_repo.upsert_sync_status = AsyncMock()
        mock_repo.project_mission = AsyncMock(return_value=SyncCounts(
            missions=1, incidents=1,
        ))

        service = MemoryService(
            phase2_client=FakePhase2Client(missions={
                "m1": make_mission(mission_id="m1"),
            }),
            phase4_client=FakePhase4Client(incidents={
                "m1": [make_incident(mission_id="m1")],
            }),
            phase5_client=FakePhase5Client(),
        )

        result = await service.sync_mission("m1", include_reasoning=False)

        assert result.status == SyncStatus.COMPLETE
        assert result.counts.missions == 1

    @pytest.mark.asyncio
    @patch("tars.phase7.service.repository")
    async def test_sync_mission_not_found(self, mock_repo):
        """Sync fails when mission doesn't exist in Phase 2."""
        mock_repo.upsert_sync_status = AsyncMock()

        service = MemoryService(
            phase2_client=FakePhase2Client(missions={}),
            phase4_client=FakePhase4Client(),
            phase5_client=FakePhase5Client(),
        )

        result = await service.sync_mission("nonexistent")

        assert result.status == SyncStatus.FAILED
        assert result.error_code == "mission_not_found"

    @pytest.mark.asyncio
    @patch("tars.phase7.service.repository")
    async def test_sync_phase5_unavailable_skip(self, mock_repo):
        """Sync succeeds with skipped reasoning when Phase 5 is unavailable."""
        mock_repo.upsert_sync_status = AsyncMock()
        mock_repo.project_mission = AsyncMock(return_value=SyncCounts(
            missions=1, incidents=1,
        ))

        service = MemoryService(
            phase2_client=FakePhase2Client(missions={
                "m1": make_mission(mission_id="m1"),
            }),
            phase4_client=FakePhase4Client(incidents={
                "m1": [make_incident(mission_id="m1")],
            }),
            phase5_client=FakePhase5Client(unavailable=True),
        )

        result = await service.sync_mission(
            "m1", include_reasoning=True, require_reasoning=False,
        )

        assert result.status == SyncStatus.COMPLETE
        assert result.counts.analyses_skipped == 1

    @pytest.mark.asyncio
    @patch("tars.phase7.service.repository")
    async def test_sync_phase5_unavailable_required(self, mock_repo):
        """Sync fails when Phase 5 is required but unavailable."""
        mock_repo.upsert_sync_status = AsyncMock()

        service = MemoryService(
            phase2_client=FakePhase2Client(missions={
                "m1": make_mission(mission_id="m1"),
            }),
            phase4_client=FakePhase4Client(incidents={
                "m1": [make_incident(mission_id="m1")],
            }),
            phase5_client=FakePhase5Client(unavailable=True),
        )

        result = await service.sync_mission(
            "m1", include_reasoning=True, require_reasoning=True,
        )

        assert result.status == SyncStatus.FAILED
        assert result.error_code == "phase5_unavailable"

    @pytest.mark.asyncio
    @patch("tars.phase7.service.repository")
    async def test_sync_no_incidents(self, mock_repo):
        """Sync succeeds for a mission with no incidents."""
        mock_repo.upsert_sync_status = AsyncMock()
        mock_repo.project_mission = AsyncMock(return_value=SyncCounts(
            missions=1,
        ))

        service = MemoryService(
            phase2_client=FakePhase2Client(missions={
                "m1": make_mission(mission_id="m1"),
            }),
            phase4_client=FakePhase4Client(incidents={"m1": []}),
            phase5_client=FakePhase5Client(),
        )

        result = await service.sync_mission("m1", include_reasoning=False)

        assert result.status == SyncStatus.COMPLETE
        assert result.counts.missions == 1
        assert result.counts.incidents == 0

    @pytest.mark.asyncio
    @patch("tars.phase7.service.repository")
    async def test_sync_idempotent(self, mock_repo):
        """Re-syncing the same mission produces the same result."""
        mock_repo.upsert_sync_status = AsyncMock()
        mock_repo.project_mission = AsyncMock(return_value=SyncCounts(
            missions=1, incidents=1,
        ))

        service = MemoryService(
            phase2_client=FakePhase2Client(missions={
                "m1": make_mission(mission_id="m1"),
            }),
            phase4_client=FakePhase4Client(incidents={
                "m1": [make_incident(mission_id="m1")],
            }),
            phase5_client=FakePhase5Client(),
        )

        result1 = await service.sync_mission("m1", include_reasoning=False)
        result2 = await service.sync_mission("m1", include_reasoning=False)

        assert result1.status == SyncStatus.COMPLETE
        assert result2.status == SyncStatus.COMPLETE
        assert mock_repo.project_mission.call_count == 2


# =============================================================================
# Observation Tests
# =============================================================================

class TestApplyMitigation:
    """Test explicit mitigation application recording."""

    @pytest.mark.asyncio
    @patch("tars.phase7.service.repository")
    async def test_apply_mitigation_success(self, mock_repo):
        """Record an applied mitigation."""
        mock_repo.record_applied_mitigation = AsyncMock(return_value={
            "application_id": "apply_001",
            "incident_id": "inc_001",
            "mitigation_id": "mit_abc",
            "description": "Switched to visual odometry",
            "applied_at": "2026-06-15T10:15:00+00:00",
            "recorded_by": "operator",
            "notes": None,
            "created": True,
        })

        service = MemoryService()
        result = await service.apply_mitigation(
            incident_id="inc_001",
            idempotency_key="apply_001",
            description="Switched to visual odometry",
            applied_at=datetime(2026, 6, 15, 10, 15, tzinfo=timezone.utc),
            recorded_by="operator",
        )

        assert result.application_id == "apply_001"
        assert result.created is True

    @pytest.mark.asyncio
    @patch("tars.phase7.service.repository")
    async def test_apply_mitigation_idempotent(self, mock_repo):
        """Duplicate idempotency key returns existing without creating."""
        mock_repo.record_applied_mitigation = AsyncMock(return_value={
            "application_id": "apply_001",
            "incident_id": "inc_001",
            "mitigation_id": "mit_abc",
            "description": "Switched to visual odometry",
            "applied_at": "2026-06-15T10:15:00+00:00",
            "recorded_by": "operator",
            "notes": None,
            "created": False,
        })

        service = MemoryService()
        result = await service.apply_mitigation(
            incident_id="inc_001",
            idempotency_key="apply_001",
            description="Switched to visual odometry",
            applied_at=datetime(2026, 6, 15, 10, 15, tzinfo=timezone.utc),
            recorded_by="operator",
        )

        assert result.created is False

    @pytest.mark.asyncio
    @patch("tars.phase7.service.repository")
    async def test_apply_mitigation_incident_not_found(self, mock_repo):
        """Applying mitigation to unknown incident raises ValueError."""
        mock_repo.record_applied_mitigation = AsyncMock(
            side_effect=ValueError("Incident 'inc_999' not found in graph")
        )

        service = MemoryService()
        with pytest.raises(ValueError, match="not found"):
            await service.apply_mitigation(
                incident_id="inc_999",
                idempotency_key="apply_001",
                description="Test",
                applied_at=datetime.now(timezone.utc),
                recorded_by="operator",
            )


class TestRecordOutcome:
    """Test explicit outcome observation recording."""

    @pytest.mark.asyncio
    @patch("tars.phase7.service.repository")
    async def test_record_outcome_success(self, mock_repo):
        """Record an outcome observation."""
        mock_repo.record_outcome = AsyncMock(return_value={
            "outcome_id": "outcome_001",
            "incident_id": "inc_001",
            "scope": "incident",
            "status": "recovered",
            "description": "Navigation stabilized",
            "observed_at": "2026-06-15T10:15:12+00:00",
            "recorded_by": "operator",
            "mitigation_application_id": None,
            "created": True,
        })

        service = MemoryService()
        result = await service.record_outcome(
            incident_id="inc_001",
            idempotency_key="outcome_001",
            status=OutcomeStatus.RECOVERED,
            description="Navigation stabilized",
            observed_at=datetime(2026, 6, 15, 10, 15, 12, tzinfo=timezone.utc),
            recorded_by="operator",
        )

        assert result.outcome_id == "outcome_001"
        assert result.status == OutcomeStatus.RECOVERED
        assert result.created is True

    @pytest.mark.asyncio
    @patch("tars.phase7.service.repository")
    async def test_record_outcome_with_mitigation_ref(self, mock_repo):
        """Record an outcome with a mitigation application reference."""
        mock_repo.record_outcome = AsyncMock(return_value={
            "outcome_id": "outcome_001",
            "incident_id": "inc_001",
            "scope": "incident",
            "status": "recovered",
            "description": "Stabilized after switching nav source",
            "observed_at": "2026-06-15T10:15:12+00:00",
            "recorded_by": "operator",
            "mitigation_application_id": "apply_001",
            "created": True,
        })

        service = MemoryService()
        result = await service.record_outcome(
            incident_id="inc_001",
            idempotency_key="outcome_001",
            status=OutcomeStatus.RECOVERED,
            description="Stabilized after switching nav source",
            observed_at=datetime(2026, 6, 15, 10, 15, 12, tzinfo=timezone.utc),
            recorded_by="operator",
            mitigation_application_id="apply_001",
        )

        assert result.mitigation_application_id == "apply_001"


# =============================================================================
# Query Tests
# =============================================================================

class TestGetIncidentMemory:
    """Test incident memory query."""

    @pytest.mark.asyncio
    @patch("tars.phase7.service.repository")
    async def test_incident_found(self, mock_repo):
        """Get incident neighborhood returns full data."""
        mock_repo.get_incident_neighborhood = AsyncMock(return_value={
            "incident": {
                "incident_id": "inc_001",
                "mission_id": "m1",
                "incident_type": "navigation_instability",
                "severity": "high",
                "start_ms": 5000,
                "end_ms": 10000,
                "peak_risk": 0.78,
                "phases": ["cruise"],
                "evidence": ["GPS degraded"],
                "source_phase": "phase4",
                "synced_at": "2026-06-15T10:30:00+00:00",
            },
            "root_causes": [
                {
                    "root_cause_id": "rc_abc",
                    "classification": "GPS interference",
                    "confidence": 0.85,
                    "reasoning_id": "r1",
                    "model": "gemini-2.5-flash",
                    "prompt_version": "v1.0",
                    "rationale": "GPS degradation pattern",
                    "uncertainties": [],
                    "source_phase": "phase5",
                },
            ],
            "recommended_mitigations": [
                {
                    "mitigation_id": "mit_abc",
                    "description": "Switch to visual odometry",
                    "advisory_only": True,
                    "source": "phase5_recommendation",
                },
            ],
            "applied_mitigations": [],
            "outcomes": [],
        })

        service = MemoryService()
        result = await service.get_incident_memory("inc_001")

        assert result is not None
        assert result.incident_id == "inc_001"
        assert len(result.root_causes) == 1
        assert len(result.recommended_mitigations) == 1
        assert len(result.applied_mitigations) == 0
        assert len(result.outcomes) == 0

    @pytest.mark.asyncio
    @patch("tars.phase7.service.repository")
    async def test_incident_not_found(self, mock_repo):
        """Get incident neighborhood returns None for unknown incident."""
        mock_repo.get_incident_neighborhood = AsyncMock(return_value=None)

        service = MemoryService()
        result = await service.get_incident_memory("nonexistent")
        assert result is None


class TestFindSimilarIncidents:
    """Test similar incident history query."""

    @pytest.mark.asyncio
    @patch("tars.phase7.service.repository")
    async def test_finds_similar(self, mock_repo):
        """Find similar incidents returns matches."""
        mock_repo.find_similar_incidents = AsyncMock(return_value={
            "query_incident_id": "inc_001",
            "matches": [
                {
                    "incident_id": "inc_002",
                    "mission_id": "m2",
                    "incident_type": "navigation_instability",
                    "severity": "high",
                    "start_ms": 3000,
                    "end_ms": 8000,
                    "peak_risk": 0.82,
                    "root_causes": [],
                    "recommended_mitigations": [],
                    "applied_mitigations": [],
                    "outcomes": [],
                },
            ],
            "total": 1,
        })

        service = MemoryService()
        result = await service.find_similar_incidents("inc_001")

        assert result.query_incident_id == "inc_001"
        assert len(result.matches) == 1
        assert result.matches[0].incident_id == "inc_002"
        assert result.total == 1

    @pytest.mark.asyncio
    @patch("tars.phase7.service.repository")
    async def test_no_similar_found(self, mock_repo):
        """Find similar incidents returns empty when none match."""
        mock_repo.find_similar_incidents = AsyncMock(return_value={
            "query_incident_id": "inc_001",
            "matches": [],
            "total": 0,
        })

        service = MemoryService()
        result = await service.find_similar_incidents("inc_001")

        assert result.total == 0
        assert result.matches == []

    @pytest.mark.asyncio
    @patch("tars.phase7.service.repository")
    async def test_limit_enforced(self, mock_repo):
        """Verify query limit is enforced."""
        mock_repo.find_similar_incidents = AsyncMock(return_value={
            "query_incident_id": "inc_001",
            "matches": [],
            "total": 0,
        })

        service = MemoryService()
        await service.find_similar_incidents("inc_001", limit=500)

        # Should be capped to max limit
        call_args = mock_repo.find_similar_incidents.call_args
        assert call_args.kwargs["limit"] <= 100


# =============================================================================
# Sync Status Tests
# =============================================================================

class TestGetSyncStatus:
    """Test sync status retrieval."""

    @pytest.mark.asyncio
    @patch("tars.phase7.service.repository")
    async def test_status_found(self, mock_repo):
        """Get sync status returns data when available."""
        mock_repo.get_sync_status = AsyncMock(return_value={
            "mission_id": "m1",
            "status": "complete",
            "started_at": "2026-06-15T10:00:00+00:00",
            "completed_at": "2026-06-15T10:00:05+00:00",
            "counts_missions": 1,
            "counts_incidents": 2,
            "counts_root_causes": 1,
            "counts_mitigations": 1,
            "counts_outcomes": 0,
            "counts_relationships": 3,
            "counts_analyses_skipped": 0,
            "error_code": None,
            "error_message": None,
        })

        service = MemoryService()
        result = await service.get_sync_status("m1")

        assert result is not None
        assert result.mission_id == "m1"
        assert result.status == SyncStatus.COMPLETE
        assert result.counts.missions == 1

    @pytest.mark.asyncio
    @patch("tars.phase7.service.repository")
    async def test_status_not_found(self, mock_repo):
        """Get sync status returns None when no sync record exists."""
        mock_repo.get_sync_status = AsyncMock(return_value=None)

        service = MemoryService()
        result = await service.get_sync_status("nonexistent")
        assert result is None
