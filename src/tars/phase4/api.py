"""
FastAPI Application -- Phase 4 Incident Engine API
===================================================
Exposes incident detection and querying endpoints.

Start with:
    PYTHONPATH=src uvicorn tars.phase4.api:app --host 0.0.0.0 --port 8003

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
    Incident,
    IncidentListResponse,
    ProcessRequest,
    ProcessResponse,
    ProcessingStatusResponse,
)
from .service import IncidentService
from .state_client import StateClient
from .store import IncidentStore

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("phase4.api")

# ---------------------------------------------------------------------------
# Application state (initialized on startup)
# ---------------------------------------------------------------------------
_store: Optional[IncidentStore] = None
_service: Optional[IncidentService] = None
_state_client: Optional[StateClient] = None


def get_service() -> IncidentService:
    """Get the IncidentService instance."""
    if _service is None:
        raise RuntimeError("IncidentService not initialized")
    return _service


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage Redis connection lifecycle."""
    global _store, _service, _state_client

    _store = IncidentStore()
    await _store.connect()

    _state_client = StateClient()
    _service = IncidentService(store=_store, state_client=_state_client)

    logger.info("Phase 4 Incident Engine started")
    logger.info("Redis: %s", settings.REDIS_URL)
    logger.info("Phase 3 API: %s", settings.PHASE3_API_URL)

    yield

    if _store is not None:
        await _store.close()
    logger.info("Phase 4 Incident Engine stopped")


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------
app = FastAPI(
    title="TARS Phase 4 -- Incident Engine API",
    description="Deterministic incident detection from mission state timelines.",
    version="0.1.0",
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------
@app.get("/health", response_model=HealthResponse)
async def health():
    """Return API, Redis, and Phase 3 readiness."""
    redis_ok = False
    if _store is not None:
        redis_ok = await _store.ping()

    phase3_ok = False
    if _state_client is not None:
        phase3_ok = await _state_client.health_check()

    return HealthResponse(
        status="ok",
        redis="ok" if redis_ok else "unavailable",
        phase3="ok" if phase3_ok else "unavailable",
    )


# ---------------------------------------------------------------------------
# Process Mission Incidents
# ---------------------------------------------------------------------------
@app.post(
    "/api/v1/incidents/process/{mission_id}",
    response_model=ProcessResponse,
)
async def process_mission(
    mission_id: str,
    request: ProcessRequest = ProcessRequest(),
):
    """
    Fetch state timeline from Phase 3 and detect incidents.

    Writes detected incidents to Redis for subsequent querying.
    """
    service = get_service()

    try:
        result = await service.process_mission(
            mission_id=mission_id,
            from_ms=request.from_ms,
            to_ms=request.to_ms,
            overwrite=request.overwrite,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Failed to process incidents for mission '{mission_id}': {exc}",
        )

    return result


# ---------------------------------------------------------------------------
# List Incidents
# ---------------------------------------------------------------------------
@app.get(
    "/api/v1/incidents/{mission_id}",
    response_model=IncidentListResponse,
)
async def list_incidents(
    mission_id: str,
    from_ms: int = Query(default=0, ge=0),
    to_ms: Optional[int] = Query(default=None, ge=0),
):
    """Return incidents for a mission within a time range."""
    service = get_service()
    return await service.get_incidents(mission_id, from_ms, to_ms)


# ---------------------------------------------------------------------------
# Get Processing Status
# (must be registered before /{incident_id} to avoid "status" matching as ID)
# ---------------------------------------------------------------------------
@app.get(
    "/api/v1/incidents/{mission_id}/status",
    response_model=ProcessingStatusResponse,
)
async def get_processing_status(mission_id: str):
    """Return processing metadata for a mission."""
    service = get_service()
    return await service.get_processing_status(mission_id)


# ---------------------------------------------------------------------------
# Get Incident
# ---------------------------------------------------------------------------
@app.get(
    "/api/v1/incidents/{mission_id}/{incident_id}",
    response_model=Incident,
)
async def get_incident(mission_id: str, incident_id: str):
    """Return a specific incident by ID."""
    service = get_service()
    incident = await service.get_incident(mission_id, incident_id)

    if incident is None:
        raise HTTPException(
            status_code=404,
            detail=f"Incident '{incident_id}' not found for mission '{mission_id}'",
        )

    return incident
