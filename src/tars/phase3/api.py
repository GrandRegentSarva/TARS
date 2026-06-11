"""
FastAPI Application -- Phase 3 State Engine API
================================================
Exposes state processing and querying endpoints.

Start with:
    PYTHONPATH=src uvicorn tars.phase3.api:app --host 0.0.0.0 --port 8002

API base path: /api/v1
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, Query

from .config import settings
from .models import (
    HealthResponse,
    ProcessRequest,
    ProcessResponse,
    ProcessingStatusResponse,
    StateSnapshot,
    TimelineResponse,
)
from .replay_client import ReplayClient
from .service import StateService
from .store import StateStore

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("phase3.api")

# ---------------------------------------------------------------------------
# Application state (initialized on startup)
# ---------------------------------------------------------------------------
_store: Optional[StateStore] = None
_service: Optional[StateService] = None


def get_service() -> StateService:
    """Get the StateService instance."""
    if _service is None:
        raise RuntimeError("StateService not initialized")
    return _service


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage Redis connection lifecycle."""
    global _store, _service

    _store = StateStore()
    await _store.connect()

    replay_client = ReplayClient()
    _service = StateService(store=_store, replay_client=replay_client)

    logger.info("Phase 3 State Engine started")
    logger.info("Redis: %s", settings.REDIS_URL)
    logger.info("Phase 2 API: %s", settings.PHASE2_API_URL)

    yield

    if _store is not None:
        await _store.close()
    logger.info("Phase 3 State Engine stopped")


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------
app = FastAPI(
    title="TARS Phase 3 -- State Engine API",
    description="Deterministic state computation from mission replay frames.",
    version="0.1.0",
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------
@app.get("/health", response_model=HealthResponse)
async def health():
    """Return API and Redis readiness."""
    redis_ok = False
    if _store is not None:
        redis_ok = await _store.ping()

    return HealthResponse(
        status="ok",
        redis="ok" if redis_ok else "unavailable",
    )


# ---------------------------------------------------------------------------
# Process Mission Replay
# ---------------------------------------------------------------------------
@app.post(
    "/api/v1/state/process/{mission_id}",
    response_model=ProcessResponse,
)
async def process_mission(
    mission_id: str,
    request: ProcessRequest = ProcessRequest(),
):
    """
    Fetch replay frames from Phase 2 and compute state snapshots.

    Writes state snapshots to Redis for subsequent querying.
    """
    service = get_service()

    try:
        result = await service.process_mission(
            mission_id=mission_id,
            from_ms=request.from_ms,
            to_ms=request.to_ms,
            speed=request.speed,
            overwrite=request.overwrite,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Failed to process mission '{mission_id}': {exc}",
        )

    return result


# ---------------------------------------------------------------------------
# Get Current State
# ---------------------------------------------------------------------------
@app.get(
    "/api/v1/state/{mission_id}/current",
    response_model=StateSnapshot,
)
async def get_current_state(mission_id: str):
    """Return the latest state snapshot for a mission."""
    service = get_service()
    state = await service.get_current_state(mission_id)

    if state is None:
        raise HTTPException(
            status_code=404,
            detail=f"No state found for mission '{mission_id}'",
        )

    return state


# ---------------------------------------------------------------------------
# Get State Timeline
# ---------------------------------------------------------------------------
@app.get(
    "/api/v1/state/{mission_id}/timeline",
    response_model=TimelineResponse,
)
async def get_timeline(
    mission_id: str,
    from_ms: int = Query(default=0, ge=0),
    to_ms: Optional[int] = Query(default=None, ge=0),
    limit: int = Query(default=1000, ge=1, le=10000),
):
    """Return state snapshots ordered by elapsed time within a range."""
    service = get_service()
    return await service.get_timeline(mission_id, from_ms, to_ms, limit)


# ---------------------------------------------------------------------------
# Get State At Time
# ---------------------------------------------------------------------------
@app.get(
    "/api/v1/state/{mission_id}/at/{elapsed_ms}",
    response_model=StateSnapshot,
)
async def get_state_at(mission_id: str, elapsed_ms: int):
    """Return the nearest state snapshot at or before elapsed_ms."""
    service = get_service()
    state = await service.get_state_at(mission_id, elapsed_ms)

    if state is None:
        raise HTTPException(
            status_code=404,
            detail=f"No state found for mission '{mission_id}' at {elapsed_ms}ms",
        )

    return state


# ---------------------------------------------------------------------------
# Get Processing Status
# ---------------------------------------------------------------------------
@app.get(
    "/api/v1/state/{mission_id}/status",
    response_model=ProcessingStatusResponse,
)
async def get_processing_status(mission_id: str):
    """Return processing metadata for a mission."""
    service = get_service()
    return await service.get_processing_status(mission_id)
