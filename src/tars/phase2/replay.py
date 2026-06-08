"""
Replay Service
==============
Converts stored telemetry rows into ordered replay frames with timing metadata.

A replay frame is a lightweight wrapper around a telemetry snapshot that
includes sequence number, elapsed time, and the full telemetry payload.
Phase 3 can consume these frames as a clean ordered stream.
"""

from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from .models.db import TelemetryEvent
from .models.schemas import ReplayFrame, ReplayResponse

logger = logging.getLogger("phase2.replay")


async def build_replay(
    session: AsyncSession,
    mission_id: str,
    speed: float = 1.0,
    from_ms: int = 0,
    to_ms: Optional[int] = None,
) -> ReplayResponse:
    """
    Build an ordered replay from stored telemetry events.

    Args:
        session:    Active async database session.
        mission_id: The mission to replay.
        speed:      Playback speed multiplier (metadata only, no delay).
        from_ms:    Start replay from this elapsed_ms (inclusive).
        to_ms:      End replay at this elapsed_ms (inclusive). None = end of mission.

    Returns:
        ReplayResponse with ordered frames and timing metadata.
    """
    # Build query with time range filters
    query = (
        select(TelemetryEvent)
        .where(TelemetryEvent.mission_id == mission_id)
        .where(TelemetryEvent.elapsed_ms >= from_ms)
    )

    if to_ms is not None:
        query = query.where(TelemetryEvent.elapsed_ms <= to_ms)

    query = query.order_by(TelemetryEvent.sequence)

    result = await session.execute(query)
    events = result.scalars().all()

    # Convert to replay frames
    frames: list[ReplayFrame] = []
    for event in events:
        frame = ReplayFrame(
            sequence=event.sequence,
            elapsed_ms=event.elapsed_ms,
            timestamp=event.timestamp,
            telemetry=event.raw,
        )
        frames.append(frame)

    return ReplayResponse(
        mission_id=mission_id,
        speed=speed,
        from_ms=from_ms,
        to_ms=to_ms,
        total_frames=len(frames),
        frames=frames,
    )
