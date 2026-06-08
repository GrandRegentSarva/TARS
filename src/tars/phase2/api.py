"""
FastAPI Application -- Phase 2 Mission Replay API
==================================================
Exposes mission listing, detail, event query, import, and replay endpoints.

Start with:
    PYTHONPATH=src uvicorn tars.phase2.api:app --host 0.0.0.0 --port 8000

API base path: /api/v1
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .database import check_database, get_session
from .importer import DuplicateMissionError, ImportError
from .models.schemas import (
    HealthResponse,
    ImportRequest,
    ImportResponse,
    MissionDetailResponse,
    MissionEventResponse,
    MissionListResponse,
    ReplayResponse,
)
from . import service

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("phase2.api")

# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------
app = FastAPI(
    title="TARS Phase 2 -- Mission Replay API",
    description="Persistence and replay layer for completed drone missions.",
    version="0.1.0",
)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------
@app.get("/health", response_model=HealthResponse)
async def health():
    """Return API and database readiness."""
    db_ok = await check_database()
    return HealthResponse(
        status="ok",
        database="ok" if db_ok else "unavailable",
    )


# ---------------------------------------------------------------------------
# Import Mission
# ---------------------------------------------------------------------------
@app.post("/api/v1/missions/import", response_model=ImportResponse)
async def import_mission(
    request: ImportRequest,
    session: AsyncSession = Depends(get_session),
):
    """Import a Phase 1 mission JSON file by local path."""
    try:
        result = await service.do_import(session, request.path, request.overwrite)
    except DuplicateMissionError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ImportError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return ImportResponse(**result)


# ---------------------------------------------------------------------------
# List Missions
# ---------------------------------------------------------------------------
@app.get("/api/v1/missions", response_model=MissionListResponse)
async def list_missions(
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    result: Optional[str] = Query(default=None, description="Filter by mission result"),
    drone_id: Optional[str] = Query(default=None, description="Filter by drone ID"),
    session: AsyncSession = Depends(get_session),
):
    """List missions with optional filtering. Returns summaries only."""
    return await service.list_missions(session, limit, offset, result, drone_id)


# ---------------------------------------------------------------------------
# Get Mission Detail
# ---------------------------------------------------------------------------
@app.get("/api/v1/missions/{mission_id}", response_model=MissionDetailResponse)
async def get_mission(
    mission_id: str,
    session: AsyncSession = Depends(get_session),
):
    """Get mission metadata, summary, and faults."""
    mission = await service.get_mission(session, mission_id)
    if mission is None:
        raise HTTPException(status_code=404, detail=f"Mission '{mission_id}' not found")
    return mission


# ---------------------------------------------------------------------------
# Get Mission Events
# ---------------------------------------------------------------------------
@app.get("/api/v1/missions/{mission_id}/events", response_model=MissionEventResponse)
async def get_mission_events(
    mission_id: str,
    limit: int = Query(default=1000, ge=1, le=10000),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
):
    """Get ordered telemetry events for a mission."""
    events = await service.get_mission_events(session, mission_id, limit, offset)
    if events is None:
        raise HTTPException(status_code=404, detail=f"Mission '{mission_id}' not found")
    return events


# ---------------------------------------------------------------------------
# Replay Mission
# ---------------------------------------------------------------------------
@app.get("/api/v1/missions/{mission_id}/replay", response_model=ReplayResponse)
async def replay_mission(
    mission_id: str,
    speed: float = Query(default=1.0, gt=0.0, le=100.0),
    from_ms: int = Query(default=0, ge=0),
    to_ms: Optional[int] = Query(default=None, ge=0),
    session: AsyncSession = Depends(get_session),
):
    """
    Replay a mission as ordered frames with elapsed timing.

    Returns a JSON array of replay frames. Each frame contains
    sequence number, elapsed_ms, timestamp, and full telemetry payload.
    """
    replay = await service.get_replay(session, mission_id, speed, from_ms, to_ms)
    if replay is None:
        raise HTTPException(status_code=404, detail=f"Mission '{mission_id}' not found")
    return replay
