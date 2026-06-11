"""
Tests for Phase 4 Redis Incident Store
========================================
Tests incident persistence, retrieval, and metadata operations.

Redis tests use DB 15 and skip if Redis is unavailable.
"""

from __future__ import annotations

import pytest
import pytest_asyncio

from tars.phase4.models import Incident, IncidentType, ProcessingStatus, Severity
from tars.phase4.store import IncidentStore

from .conftest import requires_redis


def _make_incident(
    incident_id: str = "inc_test123",
    mission_id: str = "test_mission",
    incident_type: IncidentType = IncidentType.NAVIGATION_INSTABILITY,
    severity: Severity = Severity.HIGH,
    start_ms: int = 5000,
    end_ms: int = 10000,
) -> Incident:
    """Build a test incident."""
    return Incident(
        incident_id=incident_id,
        mission_id=mission_id,
        incident_type=incident_type,
        severity=severity,
        start_sequence=5,
        end_sequence=10,
        start_ms=start_ms,
        end_ms=end_ms,
        contributing_states=6,
        peak_risk=0.75,
        phases=["cruise"],
        evidence=["GPS signal weak during flight"],
    )


@requires_redis
class TestReplaceAndGetIncidents:
    """Test incident write and read operations."""

    @pytest.mark.asyncio
    async def test_replace_and_get(self, incident_store: IncidentStore):
        incidents = [
            _make_incident("inc_1", start_ms=1000, end_ms=3000),
            _make_incident("inc_2", start_ms=5000, end_ms=8000),
        ]
        await incident_store.replace_incidents("test_mission", incidents)
        result = await incident_store.get_incidents("test_mission")
        assert len(result) == 2
        assert result[0].incident_id == "inc_1"
        assert result[1].incident_id == "inc_2"

    @pytest.mark.asyncio
    async def test_replace_overwrites(self, incident_store: IncidentStore):
        old = [_make_incident("inc_old", start_ms=1000, end_ms=2000)]
        new = [_make_incident("inc_new", start_ms=3000, end_ms=4000)]
        await incident_store.replace_incidents("test_mission", old)
        await incident_store.replace_incidents("test_mission", new)
        result = await incident_store.get_incidents("test_mission")
        assert len(result) == 1
        assert result[0].incident_id == "inc_new"

    @pytest.mark.asyncio
    async def test_get_empty(self, incident_store: IncidentStore):
        result = await incident_store.get_incidents("nonexistent")
        assert result == []

    @pytest.mark.asyncio
    async def test_get_with_time_range(self, incident_store: IncidentStore):
        incidents = [
            _make_incident("inc_1", start_ms=1000, end_ms=3000),
            _make_incident("inc_2", start_ms=5000, end_ms=8000),
            _make_incident("inc_3", start_ms=10000, end_ms=12000),
        ]
        await incident_store.replace_incidents("test_mission", incidents)
        result = await incident_store.get_incidents(
            "test_mission", from_ms=4000, to_ms=9000,
        )
        assert len(result) == 1
        assert result[0].incident_id == "inc_2"


@requires_redis
class TestGetIncident:
    """Test single incident retrieval by ID."""

    @pytest.mark.asyncio
    async def test_get_existing(self, incident_store: IncidentStore):
        incidents = [_make_incident("inc_target", start_ms=5000, end_ms=8000)]
        await incident_store.replace_incidents("test_mission", incidents)
        result = await incident_store.get_incident("test_mission", "inc_target")
        assert result is not None
        assert result.incident_id == "inc_target"

    @pytest.mark.asyncio
    async def test_get_nonexistent(self, incident_store: IncidentStore):
        result = await incident_store.get_incident("test_mission", "inc_nope")
        assert result is None


@requires_redis
class TestProcessingMetadata:
    """Test processing status operations."""

    @pytest.mark.asyncio
    async def test_set_and_get_status(self, incident_store: IncidentStore):
        await incident_store.set_status(
            "test_mission",
            ProcessingStatus.COMPLETE,
            states_evaluated="100",
            incidents_detected="3",
        )
        meta = await incident_store.get_status("test_mission")
        assert meta["status"] == "complete"
        assert meta["states_evaluated"] == "100"
        assert meta["incidents_detected"] == "3"

    @pytest.mark.asyncio
    async def test_get_empty_status(self, incident_store: IncidentStore):
        meta = await incident_store.get_status("nonexistent")
        assert meta == {}

    @pytest.mark.asyncio
    async def test_status_update(self, incident_store: IncidentStore):
        await incident_store.set_status(
            "test_mission", ProcessingStatus.PROCESSING,
        )
        await incident_store.set_status(
            "test_mission", ProcessingStatus.COMPLETE,
            states_evaluated="50",
        )
        meta = await incident_store.get_status("test_mission")
        assert meta["status"] == "complete"
        assert meta["states_evaluated"] == "50"


@requires_redis
class TestClearIncidents:
    """Test incident cleanup."""

    @pytest.mark.asyncio
    async def test_clear(self, incident_store: IncidentStore):
        incidents = [_make_incident("inc_1")]
        await incident_store.replace_incidents("test_mission", incidents)
        await incident_store.set_status(
            "test_mission", ProcessingStatus.COMPLETE,
        )
        await incident_store.clear_incidents("test_mission")
        result = await incident_store.get_incidents("test_mission")
        assert result == []
        meta = await incident_store.get_status("test_mission")
        assert meta == {}
