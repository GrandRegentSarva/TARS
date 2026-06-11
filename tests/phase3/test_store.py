"""
Redis Store Tests
=================
Tests for Redis state storage operations.

These tests require a running Redis instance and use DB 15 for isolation.
They are automatically skipped if Redis is not reachable.

Coverage:
- Set and get current state
- Append and read timeline
- Timeline preserves sequence order
- State-at-time returns nearest prior snapshot
- Processing metadata set and get
- Clear mission state removes all keys
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta

import pytest

from tars.phase3.models import (
    HealthStatus,
    MissionPhase,
    ProcessingStatus,
    SignalIndicators,
    SignalQuality,
    StateMetrics,
    StateSnapshot,
)
from tars.phase3.store import StateStore


pytestmark = pytest.mark.asyncio


def _make_snapshot(
    mission_id: str = "test_mission",
    sequence: int = 0,
    elapsed_ms: int = 0,
    phase: MissionPhase = MissionPhase.CRUISE,
    health: HealthStatus = HealthStatus.NOMINAL,
    risk: float = 0.1,
) -> StateSnapshot:
    """Build a StateSnapshot for testing."""
    return StateSnapshot(
        mission_id=mission_id,
        sequence=sequence,
        timestamp=datetime(2026, 6, 8, 6, 30, 0, tzinfo=timezone.utc)
        + timedelta(milliseconds=elapsed_ms),
        elapsed_ms=elapsed_ms,
        phase=phase,
        health=health,
        risk=risk,
        signals=SignalIndicators(),
        metrics=StateMetrics(
            relative_altitude_m=20.0,
            ground_speed_m_s=5.0,
            battery_percent=85.0,
            gps_satellites=12,
        ),
        reasons=[],
    )


class TestCurrentState:
    """Test current state read/write."""

    async def test_set_and_get_current_state(self, redis_store: StateStore):
        """Set current state and read it back."""
        snapshot = _make_snapshot()
        await redis_store.set_current_state("test_mission", snapshot)

        result = await redis_store.get_current_state("test_mission")
        assert result is not None
        assert result.mission_id == "test_mission"
        assert result.sequence == 0
        assert result.phase == MissionPhase.CRUISE

    async def test_get_missing_current_state(self, redis_store: StateStore):
        """Get current state for non-existent mission returns None."""
        result = await redis_store.get_current_state("nonexistent")
        assert result is None

    async def test_overwrite_current_state(self, redis_store: StateStore):
        """Setting current state overwrites previous value."""
        snap1 = _make_snapshot(sequence=0)
        snap2 = _make_snapshot(sequence=5, elapsed_ms=5000)

        await redis_store.set_current_state("test_mission", snap1)
        await redis_store.set_current_state("test_mission", snap2)

        result = await redis_store.get_current_state("test_mission")
        assert result is not None
        assert result.sequence == 5


class TestTimeline:
    """Test timeline sorted set operations."""

    async def test_append_and_read_timeline(self, redis_store: StateStore):
        """Append snapshots and read them back in order."""
        for i in range(5):
            snap = _make_snapshot(sequence=i, elapsed_ms=i * 1000)
            await redis_store.append_state("test_mission", snap)

        timeline = await redis_store.get_timeline("test_mission")
        assert len(timeline) == 5
        for i, snap in enumerate(timeline):
            assert snap.sequence == i
            assert snap.elapsed_ms == i * 1000

    async def test_timeline_preserves_order(self, redis_store: StateStore):
        """Timeline entries are ordered by elapsed_ms."""
        # Insert out of order
        for i in [3, 1, 4, 0, 2]:
            snap = _make_snapshot(sequence=i, elapsed_ms=i * 1000)
            await redis_store.append_state("test_mission", snap)

        timeline = await redis_store.get_timeline("test_mission")
        elapsed_values = [s.elapsed_ms for s in timeline]
        assert elapsed_values == sorted(elapsed_values)

    async def test_timeline_with_range(self, redis_store: StateStore):
        """Timeline query with from_ms and to_ms filters correctly."""
        for i in range(10):
            snap = _make_snapshot(sequence=i, elapsed_ms=i * 1000)
            await redis_store.append_state("test_mission", snap)

        timeline = await redis_store.get_timeline(
            "test_mission", from_ms=2000, to_ms=5000
        )
        assert len(timeline) == 4  # 2000, 3000, 4000, 5000
        assert timeline[0].elapsed_ms == 2000
        assert timeline[-1].elapsed_ms == 5000

    async def test_timeline_with_limit(self, redis_store: StateStore):
        """Timeline query respects limit parameter."""
        for i in range(10):
            snap = _make_snapshot(sequence=i, elapsed_ms=i * 1000)
            await redis_store.append_state("test_mission", snap)

        timeline = await redis_store.get_timeline("test_mission", limit=3)
        assert len(timeline) == 3

    async def test_empty_timeline(self, redis_store: StateStore):
        """Empty timeline returns empty list."""
        timeline = await redis_store.get_timeline("nonexistent")
        assert timeline == []


class TestStateAt:
    """Test state-at-time queries."""

    async def test_state_at_exact_time(self, redis_store: StateStore):
        """State at exact elapsed_ms returns that snapshot."""
        for i in range(5):
            snap = _make_snapshot(sequence=i, elapsed_ms=i * 1000)
            await redis_store.append_state("test_mission", snap)

        result = await redis_store.get_state_at("test_mission", 3000)
        assert result is not None
        assert result.elapsed_ms == 3000
        assert result.sequence == 3

    async def test_state_at_between_times(self, redis_store: StateStore):
        """State at time between snapshots returns nearest prior."""
        for i in range(5):
            snap = _make_snapshot(sequence=i, elapsed_ms=i * 1000)
            await redis_store.append_state("test_mission", snap)

        result = await redis_store.get_state_at("test_mission", 2500)
        assert result is not None
        assert result.elapsed_ms == 2000  # Nearest prior

    async def test_state_at_before_first(self, redis_store: StateStore):
        """State at time before first snapshot returns None."""
        snap = _make_snapshot(sequence=0, elapsed_ms=1000)
        await redis_store.append_state("test_mission", snap)

        result = await redis_store.get_state_at("test_mission", 500)
        assert result is None

    async def test_state_at_missing_mission(self, redis_store: StateStore):
        """State at time for non-existent mission returns None."""
        result = await redis_store.get_state_at("nonexistent", 1000)
        assert result is None


class TestProcessingMetadata:
    """Test processing status metadata."""

    async def test_set_and_get_status(self, redis_store: StateStore):
        """Set processing status and read it back."""
        await redis_store.set_status(
            "test_mission",
            ProcessingStatus.PROCESSING,
            frames_processed="0",
            started_at="2026-06-08T06:30:00Z",
        )

        meta = await redis_store.get_status("test_mission")
        assert meta["status"] == "processing"
        assert meta["frames_processed"] == "0"
        assert meta["started_at"] == "2026-06-08T06:30:00Z"

    async def test_update_status(self, redis_store: StateStore):
        """Updating status preserves existing fields."""
        await redis_store.set_status(
            "test_mission",
            ProcessingStatus.PROCESSING,
            frames_processed="0",
            started_at="2026-06-08T06:30:00Z",
        )

        await redis_store.set_status(
            "test_mission",
            ProcessingStatus.COMPLETE,
            frames_processed="42",
            completed_at="2026-06-08T06:31:00Z",
        )

        meta = await redis_store.get_status("test_mission")
        assert meta["status"] == "complete"
        assert meta["frames_processed"] == "42"
        assert meta["started_at"] == "2026-06-08T06:30:00Z"

    async def test_get_missing_status(self, redis_store: StateStore):
        """Get status for non-existent mission returns empty dict."""
        meta = await redis_store.get_status("nonexistent")
        assert meta == {}


class TestClearState:
    """Test state cleanup."""

    async def test_clear_removes_all_keys(self, redis_store: StateStore):
        """Clear mission state removes current, timeline, and meta."""
        snap = _make_snapshot()
        await redis_store.set_current_state("test_mission", snap)
        await redis_store.append_state("test_mission", snap)
        await redis_store.set_status(
            "test_mission", ProcessingStatus.COMPLETE
        )

        await redis_store.clear_mission_state("test_mission")

        assert await redis_store.get_current_state("test_mission") is None
        assert await redis_store.get_timeline("test_mission") == []
        assert await redis_store.get_status("test_mission") == {}
