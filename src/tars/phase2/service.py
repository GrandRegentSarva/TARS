"""
Mission Service
===============
Orchestration layer between the API and the database/importer/replay modules.

Handles:
- Mission listing with filtering and pagination
- Mission detail retrieval (metadata + faults)
- Mission event retrieval with pagination
- Import delegation to the importer module
- Replay delegation to the replay module
"""

from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from .models.db import FaultEvent, Mission, TelemetryEvent
from .models.schemas import (
    FaultEventSchema,
    MissionDetailResponse,
    MissionEventResponse,
    MissionEventSchema,
    MissionListResponse,
    MissionSummarySchema,
    ReplayResponse,
)
from .importer import import_mission
from .replay import build_replay

logger = logging.getLogger("phase2.service")


async def list_missions(
    session: AsyncSession,
    limit: int = 50,
    offset: int = 0,
    result: Optional[str] = None,
    drone_id: Optional[str] = None,
) -> MissionListResponse:
    """
    List missions with optional filtering and pagination.

    Returns mission summaries only -- no telemetry arrays.
    """
    # Base query
    query = select(Mission)

    # Optional filters
    if result is not None:
        query = query.where(Mission.mission_result == result)
    if drone_id is not None:
        query = query.where(Mission.drone_id == drone_id)

    # Count total matching missions
    count_query = select(func.count()).select_from(query.subquery())
    total_result = await session.execute(count_query)
    total = total_result.scalar_one()

    # Apply pagination and ordering
    query = query.order_by(Mission.start_time.desc()).offset(offset).limit(limit)

    result_rows = await session.execute(query)
    missions = result_rows.scalars().all()

    return MissionListResponse(
        missions=[MissionSummarySchema.model_validate(m) for m in missions],
        total=total,
        limit=limit,
        offset=offset,
    )


async def get_mission(
    session: AsyncSession,
    mission_id: str,
) -> Optional[MissionDetailResponse]:
    """
    Get a single mission with metadata, summary, and faults.

    Returns None if the mission does not exist.
    """
    query = (
        select(Mission)
        .where(Mission.mission_id == mission_id)
        .options(selectinload(Mission.fault_events))
    )
    result = await session.execute(query)
    mission = result.scalar_one_or_none()

    if mission is None:
        return None

    return MissionDetailResponse(
        mission_id=mission.mission_id,
        drone_id=mission.drone_id,
        start_time=mission.start_time,
        end_time=mission.end_time,
        mission_result=mission.mission_result,
        summary=mission.summary,
        source_file=mission.source_file,
        created_at=mission.created_at,
        faults=[FaultEventSchema.model_validate(f) for f in mission.fault_events],
    )


async def get_mission_events(
    session: AsyncSession,
    mission_id: str,
    limit: int = 1000,
    offset: int = 0,
) -> Optional[MissionEventResponse]:
    """
    Get ordered telemetry events for a mission with pagination.

    Returns None if the mission does not exist.
    """
    # Verify mission exists
    mission_check = await session.execute(
        select(Mission.mission_id).where(Mission.mission_id == mission_id)
    )
    if mission_check.scalar_one_or_none() is None:
        return None

    # Count total events
    count_query = select(func.count()).where(TelemetryEvent.mission_id == mission_id)
    total_result = await session.execute(count_query)
    total = total_result.scalar_one()

    # Fetch events with pagination
    query = (
        select(TelemetryEvent)
        .where(TelemetryEvent.mission_id == mission_id)
        .order_by(TelemetryEvent.sequence)
        .offset(offset)
        .limit(limit)
    )
    result = await session.execute(query)
    events = result.scalars().all()

    return MissionEventResponse(
        mission_id=mission_id,
        events=[MissionEventSchema.model_validate(e) for e in events],
        total=total,
        limit=limit,
        offset=offset,
    )


async def do_import(
    session: AsyncSession,
    file_path: str,
    overwrite: bool = False,
) -> dict:
    """
    Import a Phase 1 mission JSON file.

    Delegates to the importer module.
    """
    return await import_mission(session, file_path, overwrite)


async def get_replay(
    session: AsyncSession,
    mission_id: str,
    speed: float = 1.0,
    from_ms: int = 0,
    to_ms: Optional[int] = None,
) -> Optional[ReplayResponse]:
    """
    Build a replay for a mission.

    Returns None if the mission does not exist.
    """
    # Verify mission exists
    mission_check = await session.execute(
        select(Mission.mission_id).where(Mission.mission_id == mission_id)
    )
    if mission_check.scalar_one_or_none() is None:
        return None

    return await build_replay(session, mission_id, speed, from_ms, to_ms)
