"""
Replay Tests
=============
Tests for the Phase 2 replay service.

Coverage:
- Replay returns frames in sequence order
- Replay frames include elapsed_ms
- Time range filtering works (from_ms, to_ms)
- Empty replay for non-existent mission events
"""

from __future__ import annotations

import json
import os
import tempfile

import pytest

from tars.phase2.importer import import_mission
from tars.phase2.replay import build_replay

from .conftest import make_sample_mission


pytestmark = pytest.mark.asyncio


async def _import_sample(db_session, num_snapshots=10):
    """Helper: import a sample mission and commit."""
    data = make_sample_mission(num_snapshots=num_snapshots)
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, dir="."
    ) as f:
        json.dump(data, f)
        path = f.name

    await import_mission(db_session, path)
    await db_session.commit()
    os.unlink(path)
    return data["mission_id"]


async def test_replay_returns_ordered_frames(db_session):
    """Replay frames are returned in sequence order."""
    mission_id = await _import_sample(db_session, num_snapshots=10)

    replay = await build_replay(db_session, mission_id)

    assert replay.mission_id == mission_id
    assert replay.total_frames == 10

    # Verify sequence ordering
    for i, frame in enumerate(replay.frames):
        assert frame.sequence == i


async def test_replay_frames_include_elapsed_ms(db_session):
    """Each replay frame includes correct elapsed_ms."""
    mission_id = await _import_sample(db_session, num_snapshots=5)

    replay = await build_replay(db_session, mission_id)

    assert replay.frames[0].elapsed_ms == 0
    assert replay.frames[1].elapsed_ms == 1000
    assert replay.frames[2].elapsed_ms == 2000
    assert replay.frames[3].elapsed_ms == 3000
    assert replay.frames[4].elapsed_ms == 4000


async def test_replay_frames_contain_telemetry(db_session):
    """Each replay frame contains the full telemetry snapshot."""
    mission_id = await _import_sample(db_session, num_snapshots=3)

    replay = await build_replay(db_session, mission_id)

    for frame in replay.frames:
        assert "position" in frame.telemetry
        assert "battery" in frame.telemetry
        assert "gps" in frame.telemetry
        assert "flight_mode" in frame.telemetry


async def test_replay_from_ms_filter(db_session):
    """Replay with from_ms filters out earlier frames."""
    mission_id = await _import_sample(db_session, num_snapshots=10)

    # Start from 5000ms (5 seconds in)
    replay = await build_replay(db_session, mission_id, from_ms=5000)

    assert replay.total_frames == 5  # frames 5,6,7,8,9
    assert replay.frames[0].elapsed_ms == 5000
    assert replay.frames[0].sequence == 5


async def test_replay_to_ms_filter(db_session):
    """Replay with to_ms filters out later frames."""
    mission_id = await _import_sample(db_session, num_snapshots=10)

    # End at 3000ms (first 4 frames: 0,1000,2000,3000)
    replay = await build_replay(db_session, mission_id, to_ms=3000)

    assert replay.total_frames == 4
    assert replay.frames[-1].elapsed_ms == 3000


async def test_replay_from_and_to_ms_filter(db_session):
    """Replay with both from_ms and to_ms returns a time window."""
    mission_id = await _import_sample(db_session, num_snapshots=10)

    replay = await build_replay(db_session, mission_id, from_ms=2000, to_ms=5000)

    assert replay.total_frames == 4  # frames at 2000, 3000, 4000, 5000
    assert replay.frames[0].elapsed_ms == 2000
    assert replay.frames[-1].elapsed_ms == 5000


async def test_replay_speed_metadata(db_session):
    """Replay response includes the requested speed."""
    mission_id = await _import_sample(db_session, num_snapshots=3)

    replay = await build_replay(db_session, mission_id, speed=2.5)

    assert replay.speed == 2.5


async def test_replay_empty_for_no_events(db_session):
    """Replay for a mission with no matching events returns empty frames."""
    mission_id = await _import_sample(db_session, num_snapshots=5)

    # Request a time range with no events
    replay = await build_replay(db_session, mission_id, from_ms=999999)

    assert replay.total_frames == 0
    assert replay.frames == []
