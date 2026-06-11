"""
Importer Tests
==============
Tests for the Phase 2 mission importer.

Coverage:
- Valid Phase 1 JSON imports successfully
- Duplicate import is rejected unless overwrite is enabled
- Events and faults are persisted correctly
- Invalid JSON is rejected
- Missing file is rejected
"""

from __future__ import annotations

import json
import os
import tempfile

import pytest
import pytest_asyncio
from sqlalchemy import select

from tars.phase2.importer import import_mission, DuplicateMissionError, ImportError
from tars.phase2.models.db import Mission, TelemetryEvent, FaultEvent

from .conftest import make_sample_mission


pytestmark = pytest.mark.asyncio


async def test_import_valid_mission(db_session, sample_mission_file):
    """A valid Phase 1 JSON file imports successfully."""
    result = await import_mission(db_session, sample_mission_file)
    await db_session.commit()

    assert result["mission_id"] == "test_mission_001"
    assert result["events_imported"] == 5
    assert result["faults_imported"] == 1
    assert result["status"] == "imported"

    # Verify mission row exists
    row = await db_session.execute(
        select(Mission).where(Mission.mission_id == "test_mission_001")
    )
    mission = row.scalar_one()
    assert mission.drone_id == "tars-sim-01"
    assert mission.mission_result == "SUCCESS"

    # Clean up temp file
    os.unlink(sample_mission_file)


async def test_import_creates_telemetry_events(db_session, sample_mission_file):
    """Import creates one telemetry_events row per snapshot."""
    await import_mission(db_session, sample_mission_file)
    await db_session.commit()

    rows = await db_session.execute(
        select(TelemetryEvent)
        .where(TelemetryEvent.mission_id == "test_mission_001")
        .order_by(TelemetryEvent.sequence)
    )
    events = rows.scalars().all()

    assert len(events) == 5
    # Verify sequence ordering
    for i, event in enumerate(events):
        assert event.sequence == i
    # Verify elapsed_ms increases
    assert events[0].elapsed_ms == 0
    assert events[1].elapsed_ms == 1000
    assert events[4].elapsed_ms == 4000

    os.unlink(sample_mission_file)


async def test_import_creates_fault_events(db_session, sample_mission_file):
    """Import creates one fault_events row per fault."""
    await import_mission(db_session, sample_mission_file)
    await db_session.commit()

    rows = await db_session.execute(
        select(FaultEvent).where(FaultEvent.mission_id == "test_mission_001")
    )
    faults = rows.scalars().all()

    assert len(faults) == 1
    assert faults[0].fault_type == "gps_block"
    assert faults[0].description == "GPS signal blocked for 5 seconds"
    assert faults[0].elapsed_ms == 2000  # 2 seconds after start

    os.unlink(sample_mission_file)


async def test_import_preserves_raw_snapshot(db_session, sample_mission_file):
    """Each telemetry event stores the full original snapshot in raw."""
    await import_mission(db_session, sample_mission_file)
    await db_session.commit()

    rows = await db_session.execute(
        select(TelemetryEvent)
        .where(TelemetryEvent.mission_id == "test_mission_001")
        .order_by(TelemetryEvent.sequence)
        .limit(1)
    )
    event = rows.scalar_one()

    # raw should contain the full snapshot
    assert "timestamp" in event.raw
    assert "position" in event.raw
    assert "battery" in event.raw

    os.unlink(sample_mission_file)


async def test_duplicate_import_rejected(db_session, sample_mission_file):
    """Re-importing the same mission_id is rejected by default."""
    await import_mission(db_session, sample_mission_file)
    await db_session.commit()

    with pytest.raises(DuplicateMissionError):
        await import_mission(db_session, sample_mission_file)

    os.unlink(sample_mission_file)


async def test_duplicate_import_with_overwrite(db_session):
    """Re-importing with overwrite=True replaces the existing mission."""
    data = make_sample_mission(num_snapshots=3)

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, dir="."
    ) as f:
        json.dump(data, f)
        path = f.name

    # First import
    result1 = await import_mission(db_session, path)
    await db_session.commit()
    assert result1["events_imported"] == 3

    # Modify and re-import with overwrite
    data["telemetry"] = data["telemetry"][:2]  # Reduce to 2 snapshots
    data["summary"]["total_snapshots"] = 2
    with open(path, "w") as f:
        json.dump(data, f)

    result2 = await import_mission(db_session, path, overwrite=True)
    await db_session.commit()
    assert result2["events_imported"] == 2

    # Verify only 2 events remain
    rows = await db_session.execute(
        select(TelemetryEvent).where(TelemetryEvent.mission_id == "test_mission_001")
    )
    assert len(rows.scalars().all()) == 2

    os.unlink(path)


async def test_import_missing_file(db_session):
    """Importing a non-existent file raises ImportError."""
    with pytest.raises(ImportError, match="File not found"):
        await import_mission(db_session, "nonexistent_file.json")


async def test_import_invalid_json(db_session):
    """Importing invalid JSON raises ImportError."""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, dir="."
    ) as f:
        f.write("not valid json {{{")
        path = f.name

    with pytest.raises(ImportError, match="Failed to read JSON"):
        await import_mission(db_session, path)

    os.unlink(path)


async def test_import_invalid_schema(db_session):
    """Importing JSON that doesn't match MissionTelemetry raises ImportError."""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, dir="."
    ) as f:
        json.dump({"not": "a mission"}, f)
        path = f.name

    with pytest.raises(ImportError, match="Validation failed"):
        await import_mission(db_session, path)

    os.unlink(path)


async def test_import_mission_without_faults(db_session):
    """A mission with no faults imports successfully."""
    data = make_sample_mission(num_faults=0)

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, dir="."
    ) as f:
        json.dump(data, f)
        path = f.name

    result = await import_mission(db_session, path)
    await db_session.commit()

    assert result["faults_imported"] == 0

    os.unlink(path)
