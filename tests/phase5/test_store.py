"""
Tests for Phase 5 Redis Reasoning Store
=========================================
Tests reasoning analysis persistence, retrieval, listing, and cleanup.

Redis tests use DB 15 and skip if Redis is unavailable.
"""

from __future__ import annotations

import pytest

from tars.phase5.models import ReasoningResult
from tars.phase5.store import ReasoningStore

from .conftest import requires_redis


def _make_result(
    reasoning_id: str = "reason_test123",
    mission_id: str = "test_mission",
    incident_id: str = "inc_test123",
    incident_type: str = "navigation_instability",
    root_cause: str = "gps_interference",
    confidence: float = 0.85,
    created_at: str = "2026-06-11T12:00:00+00:00",
) -> ReasoningResult:
    """Build a test reasoning result."""
    return ReasoningResult(
        reasoning_id=reasoning_id,
        mission_id=mission_id,
        incident_id=incident_id,
        incident_type=incident_type,
        root_cause=root_cause,
        confidence=confidence,
        recommendation="consider switching to visual navigation",
        rationale="GPS degradation preceded attitude instability.",
        contributing_factors=["weak GPS quality during cruise"],
        uncertainties=["No environmental data available"],
        model="fake-gemini-test",
        prompt_version="1.0.0",
        created_at=created_at,
        advisory_only=True,
    )


@requires_redis
class TestSaveAndGetAnalysis:
    """Test analysis save and retrieval."""

    @pytest.mark.asyncio
    async def test_save_and_get(self, reasoning_store: ReasoningStore):
        result = _make_result()
        await reasoning_store.save_analysis(
            "test_mission", "inc_test123", result
        )
        retrieved = await reasoning_store.get_analysis(
            "test_mission", "inc_test123"
        )
        assert retrieved is not None
        assert retrieved.reasoning_id == "reason_test123"
        assert retrieved.root_cause == "gps_interference"
        assert retrieved.confidence == 0.85

    @pytest.mark.asyncio
    async def test_get_nonexistent(self, reasoning_store: ReasoningStore):
        result = await reasoning_store.get_analysis(
            "test_mission", "inc_nonexistent"
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_replace_analysis(self, reasoning_store: ReasoningStore):
        old = _make_result(reasoning_id="reason_old", confidence=0.5)
        new = _make_result(reasoning_id="reason_new", confidence=0.9)

        await reasoning_store.save_analysis(
            "test_mission", "inc_test123", old
        )
        await reasoning_store.save_analysis(
            "test_mission", "inc_test123", new
        )

        retrieved = await reasoning_store.get_analysis(
            "test_mission", "inc_test123"
        )
        assert retrieved is not None
        assert retrieved.reasoning_id == "reason_new"
        assert retrieved.confidence == 0.9


@requires_redis
class TestListAnalyses:
    """Test listing analyses for a mission."""

    @pytest.mark.asyncio
    async def test_list_multiple(self, reasoning_store: ReasoningStore):
        r1 = _make_result(
            reasoning_id="reason_1",
            incident_id="inc_1",
            created_at="2026-06-11T12:00:00+00:00",
        )
        r2 = _make_result(
            reasoning_id="reason_2",
            incident_id="inc_2",
            created_at="2026-06-11T12:01:00+00:00",
        )
        await reasoning_store.save_analysis("test_mission", "inc_1", r1)
        await reasoning_store.save_analysis("test_mission", "inc_2", r2)

        analyses = await reasoning_store.list_analyses("test_mission")
        assert len(analyses) == 2
        # Should be sorted by created_at
        assert analyses[0].reasoning_id == "reason_1"
        assert analyses[1].reasoning_id == "reason_2"

    @pytest.mark.asyncio
    async def test_list_empty(self, reasoning_store: ReasoningStore):
        analyses = await reasoning_store.list_analyses("nonexistent")
        assert analyses == []

    @pytest.mark.asyncio
    async def test_list_isolates_missions(self, reasoning_store: ReasoningStore):
        r1 = _make_result(
            reasoning_id="reason_m1",
            mission_id="mission_a",
            incident_id="inc_1",
        )
        r2 = _make_result(
            reasoning_id="reason_m2",
            mission_id="mission_b",
            incident_id="inc_2",
        )
        await reasoning_store.save_analysis("mission_a", "inc_1", r1)
        await reasoning_store.save_analysis("mission_b", "inc_2", r2)

        analyses_a = await reasoning_store.list_analyses("mission_a")
        analyses_b = await reasoning_store.list_analyses("mission_b")

        assert len(analyses_a) == 1
        assert analyses_a[0].reasoning_id == "reason_m1"
        assert len(analyses_b) == 1
        assert analyses_b[0].reasoning_id == "reason_m2"


@requires_redis
class TestClearAnalyses:
    """Test analysis cleanup."""

    @pytest.mark.asyncio
    async def test_clear(self, reasoning_store: ReasoningStore):
        result = _make_result()
        await reasoning_store.save_analysis(
            "test_mission", "inc_test123", result
        )
        await reasoning_store.clear_analyses("test_mission")

        retrieved = await reasoning_store.get_analysis(
            "test_mission", "inc_test123"
        )
        assert retrieved is None

        analyses = await reasoning_store.list_analyses("test_mission")
        assert analyses == []

    @pytest.mark.asyncio
    async def test_clear_does_not_affect_other_missions(
        self, reasoning_store: ReasoningStore
    ):
        r1 = _make_result(reasoning_id="reason_1", incident_id="inc_1")
        r2 = _make_result(reasoning_id="reason_2", incident_id="inc_2")
        await reasoning_store.save_analysis("mission_a", "inc_1", r1)
        await reasoning_store.save_analysis("mission_b", "inc_2", r2)

        await reasoning_store.clear_analyses("mission_a")

        analyses_a = await reasoning_store.list_analyses("mission_a")
        analyses_b = await reasoning_store.list_analyses("mission_b")
        assert len(analyses_a) == 0
        assert len(analyses_b) == 1


@requires_redis
class TestPing:
    """Test Redis connectivity check."""

    @pytest.mark.asyncio
    async def test_ping(self, reasoning_store: ReasoningStore):
        assert await reasoning_store.ping() is True
