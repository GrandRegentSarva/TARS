"""
Mission Importer
================
Loads Phase 1 mission JSON files, validates them through the canonical
MissionTelemetry Pydantic model, and persists missions, telemetry events,
and fault events into PostgreSQL.

Import flow:
1. Read JSON file from disk.
2. Validate with tars.phase1.models.telemetry.MissionTelemetry.
3. Check for duplicate mission_id (reject unless overwrite=True).
4. Insert one missions row.
5. Insert one telemetry_events row per snapshot.
6. Insert one fault_events row per fault.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from tars.phase1.models.telemetry import MissionTelemetry

from .models.db import FaultEvent, Mission, TelemetryEvent

logger = logging.getLogger("phase2.importer")


class ImportError(Exception):
    """Raised when a mission import fails."""
    pass


class DuplicateMissionError(ImportError):
    """Raised when a mission_id already exists and overwrite is False."""
    pass


async def import_mission(
    session: AsyncSession,
    file_path: str,
    overwrite: bool = False,
) -> dict:
    """
    Import a Phase 1 mission JSON file into the database.

    Args:
        session:   Active async database session.
        file_path: Path to the Phase 1 mission JSON file.
        overwrite: If True, delete existing mission data before re-importing.

    Returns:
        Dict with mission_id, events_imported, faults_imported, status.

    Raises:
        ImportError:          If the file cannot be read or validated.
        DuplicateMissionError: If mission_id exists and overwrite is False.
    """
    path = Path(file_path)

    # ------------------------------------------------------------------
    # 1. Read JSON file
    # ------------------------------------------------------------------
    if not path.exists():
        raise ImportError(f"File not found: {file_path}")

    try:
        raw_json = path.read_text(encoding="utf-8")
        data = json.loads(raw_json)
    except (json.JSONDecodeError, OSError) as exc:
        raise ImportError(f"Failed to read JSON file: {exc}") from exc

    # ------------------------------------------------------------------
    # 2. Validate with Phase 1 MissionTelemetry model
    # ------------------------------------------------------------------
    try:
        mission_data = MissionTelemetry.model_validate(data)
    except Exception as exc:
        raise ImportError(f"Validation failed: {exc}") from exc

    mission_id = mission_data.mission_id

    # ------------------------------------------------------------------
    # 3. Check for duplicates
    # ------------------------------------------------------------------
    existing = await session.execute(
        select(Mission).where(Mission.mission_id == mission_id)
    )
    existing_mission = existing.scalar_one_or_none()

    if existing_mission is not None:
        if not overwrite:
            raise DuplicateMissionError(
                f"Mission '{mission_id}' already exists. "
                f"Set overwrite=true to replace it."
            )
        # Delete existing data (cascade will remove events and faults)
        await session.execute(
            delete(TelemetryEvent).where(TelemetryEvent.mission_id == mission_id)
        )
        await session.execute(
            delete(FaultEvent).where(FaultEvent.mission_id == mission_id)
        )
        await session.execute(
            delete(Mission).where(Mission.mission_id == mission_id)
        )
        await session.flush()
        logger.info(f"Deleted existing mission '{mission_id}' for overwrite")

    # ------------------------------------------------------------------
    # 4. Insert mission row
    # ------------------------------------------------------------------
    summary_dict = None
    if mission_data.summary is not None:
        summary_dict = mission_data.summary.model_dump(mode="json")

    mission_row = Mission(
        mission_id=mission_id,
        drone_id=mission_data.drone_id,
        start_time=mission_data.start_time,
        end_time=mission_data.end_time,
        mission_result=mission_data.mission_result.value,
        summary=summary_dict,
        source_file=str(path),
    )
    session.add(mission_row)
    await session.flush()

    # ------------------------------------------------------------------
    # 5. Insert telemetry event rows
    # ------------------------------------------------------------------
    events_imported = 0
    for seq, snapshot in enumerate(mission_data.telemetry):
        # Compute elapsed_ms from mission start
        elapsed_ms = 0
        if snapshot.timestamp and mission_data.start_time:
            delta = snapshot.timestamp - mission_data.start_time
            elapsed_ms = int(delta.total_seconds() * 1000)

        # Build raw snapshot dict for forward compatibility
        raw = snapshot.model_dump(mode="json")

        event_row = TelemetryEvent(
            mission_id=mission_id,
            sequence=seq,
            timestamp=snapshot.timestamp,
            elapsed_ms=elapsed_ms,
            position=snapshot.position.model_dump(mode="json") if snapshot.position else None,
            velocity=snapshot.velocity.model_dump(mode="json") if snapshot.velocity else None,
            battery=snapshot.battery.model_dump(mode="json") if snapshot.battery else None,
            gps=snapshot.gps.model_dump(mode="json") if snapshot.gps else None,
            attitude=snapshot.attitude.model_dump(mode="json") if snapshot.attitude else None,
            flight_mode=snapshot.flight_mode,
            health=snapshot.health.model_dump(mode="json") if snapshot.health else None,
            raw=raw,
        )
        session.add(event_row)
        events_imported += 1

    # ------------------------------------------------------------------
    # 6. Insert fault event rows
    # ------------------------------------------------------------------
    faults_imported = 0
    for fault in mission_data.faults_injected:
        elapsed_ms = None
        if fault.triggered_at and mission_data.start_time:
            delta = fault.triggered_at - mission_data.start_time
            elapsed_ms = int(delta.total_seconds() * 1000)

        fault_row = FaultEvent(
            mission_id=mission_id,
            fault_type=fault.fault_type.value,
            triggered_at=fault.triggered_at,
            elapsed_ms=elapsed_ms,
            parameters=fault.parameters,
            description=fault.description,
        )
        session.add(fault_row)
        faults_imported += 1

    await session.flush()

    logger.info(
        f"Imported mission '{mission_id}': "
        f"{events_imported} events, {faults_imported} faults"
    )

    return {
        "mission_id": mission_id,
        "events_imported": events_imported,
        "faults_imported": faults_imported,
        "status": "imported",
    }
