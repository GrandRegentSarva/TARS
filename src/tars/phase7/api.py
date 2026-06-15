"""
FastAPI Application -- Phase 7 Operational Memory API
=====================================================
Exposes mission memory synchronization, observation recording,
and graph-backed history query endpoints.

Start with:
    PYTHONPATH=src uvicorn tars.phase7.api:app --host 0.0.0.0 --port 8005

API base path: /api/v1
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, Query

from .config import settings
from .database import check_connectivity, close_driver, init_driver
from .models import (
    ApplyMitigationRequest,
    ApplyMitigationResponse,
    HealthResponse,
    IncidentMemoryResponse,
    RecordOutcomeRequest,
    RecordOutcomeResponse,
    SimilarHistoryResponse,
    SyncRequest,
    SyncResponse,
    SyncStatusResponse,
)
from .schema import check_schema_ready, init_schema
from .service import MemoryService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("phase7.api")

# ---------------------------------------------------------------------------
# Application state (initialized on startup)
# ---------------------------------------------------------------------------
_service: Optional[MemoryService] = None
_schema_ready: bool = False


def get_service() -> MemoryService:
    """Get the MemoryService instance."""
    if _service is None:
        raise RuntimeError("MemoryService not initialized")
    return _service


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage Neo4j driver lifecycle and schema initialization."""
    global _service, _schema_ready

    try:
        await init_driver()
        logger.info("Neo4j driver initialized")

        # Initialize schema (constraints and indexes)
        try:
            await init_schema()
            _schema_ready = await check_schema_ready()
            logger.info("Neo4j schema ready: %s", _schema_ready)
        except Exception as exc:
            logger.warning(
                "Neo4j schema initialization failed: %s. "
                "API will start with degraded functionality.",
                exc,
            )
            _schema_ready = False

    except Exception as exc:
        logger.warning(
            "Neo4j driver initialization failed: %s. "
            "API will start with unavailable Neo4j.",
            exc,
        )

    _service = MemoryService()

    logger.info("Phase 7 Operational Memory API started")
    logger.info("Neo4j: %s", settings.NEO4J_URI)
    logger.info("Phase 2 API: %s", settings.PHASE2_API_URL)
    logger.info("Phase 4 API: %s", settings.PHASE4_API_URL)
    logger.info("Phase 5 API: %s", settings.PHASE5_API_URL)

    yield

    await close_driver()
    logger.info("Phase 7 Operational Memory API stopped")


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------
app = FastAPI(
    title="TARS Phase 7 -- Operational Memory API",
    description=(
        "Neo4j-backed operational memory connecting missions, incidents, "
        "root causes, mitigations, and outcomes."
    ),
    version="0.1.0",
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------
@app.get("/health", response_model=HealthResponse)
async def health():
    """Return API, Neo4j, and upstream API readiness."""
    neo4j_ok = await check_connectivity()

    service = _service
    phase2_ok = False
    phase4_ok = False
    phase5_ok = False

    if service is not None:
        try:
            phase2_ok = await service._phase2.health_check()
        except Exception:
            pass
        try:
            phase4_ok = await service._phase4.health_check()
        except Exception:
            pass
        try:
            phase5_ok = await service._phase5.health_check()
        except Exception:
            pass

    return HealthResponse(
        status="ok" if neo4j_ok else "degraded",
        neo4j="ok" if neo4j_ok else "unavailable",
        schema_ready=_schema_ready,
        phase2="ok" if phase2_ok else "unavailable",
        phase4="ok" if phase4_ok else "unavailable",
        phase5="ok" if phase5_ok else "unavailable",
    )


# ---------------------------------------------------------------------------
# Sync Mission Memory
# ---------------------------------------------------------------------------
@app.post(
    "/api/v1/memory/sync/{mission_id}",
    response_model=SyncResponse,
)
async def sync_mission(
    mission_id: str,
    request: SyncRequest = SyncRequest(),
):
    """
    Synchronize a completed mission into the operational memory graph.

    Fetches bounded data from Phase 2, Phase 4, and optionally Phase 5,
    then writes one idempotent graph transaction.
    """
    neo4j_ok = await check_connectivity()
    if not neo4j_ok:
        raise HTTPException(
            status_code=503,
            detail="Neo4j is unavailable. Cannot sync mission memory.",
        )

    service = get_service()
    result = await service.sync_mission(
        mission_id=mission_id,
        include_reasoning=request.include_reasoning,
        require_reasoning=request.require_reasoning,
    )

    if result.error_code == "mission_not_found":
        raise HTTPException(status_code=404, detail=result.error_message)

    if result.error_code in ("phase2_unavailable", "phase4_unavailable"):
        raise HTTPException(status_code=502, detail=result.error_message)

    if result.error_code in ("phase5_unavailable", "phase5_error") and request.require_reasoning:
        raise HTTPException(status_code=502, detail=result.error_message)

    if result.error_code == "mapping_error":
        raise HTTPException(status_code=422, detail=result.error_message)

    if result.error_code == "internal_error":
        raise HTTPException(status_code=500, detail=result.error_message)

    if result.error_code in ("phase4_error",):
        raise HTTPException(status_code=502, detail=result.error_message)

    return result


# ---------------------------------------------------------------------------
# Sync Status
# ---------------------------------------------------------------------------
@app.get(
    "/api/v1/memory/sync/{mission_id}",
    response_model=SyncStatusResponse,
)
async def get_sync_status(mission_id: str):
    """Return the latest sync status for a mission."""
    service = get_service()

    neo4j_ok = await check_connectivity()
    if not neo4j_ok:
        raise HTTPException(
            status_code=503,
            detail="Neo4j is unavailable.",
        )

    result = await service.get_sync_status(mission_id)
    if result is None:
        raise HTTPException(
            status_code=404,
            detail=f"No sync record found for mission '{mission_id}'",
        )

    return result


# ---------------------------------------------------------------------------
# Incident Memory
# ---------------------------------------------------------------------------
@app.get(
    "/api/v1/memory/incidents/{incident_id}",
    response_model=IncidentMemoryResponse,
)
async def get_incident_memory(incident_id: str):
    """Return the bounded graph neighborhood for one incident."""
    neo4j_ok = await check_connectivity()
    if not neo4j_ok:
        raise HTTPException(
            status_code=503,
            detail="Neo4j is unavailable.",
        )

    service = get_service()
    result = await service.get_incident_memory(incident_id)
    if result is None:
        raise HTTPException(
            status_code=404,
            detail=f"Incident '{incident_id}' not found in operational memory",
        )

    return result


# ---------------------------------------------------------------------------
# Similar History
# ---------------------------------------------------------------------------
@app.get(
    "/api/v1/memory/incidents/{incident_id}/similar",
    response_model=SimilarHistoryResponse,
)
async def get_similar_incidents(
    incident_id: str,
    limit: int = Query(
        default=settings.MEMORY_QUERY_DEFAULT_LIMIT,
        ge=1,
        le=settings.MEMORY_QUERY_MAX_LIMIT,
    ),
):
    """
    Find similar incidents based on deterministic matching.

    Returns prior incidents with the same type, ranked by severity match,
    shared root-cause classification, and recency.
    """
    service = get_service()

    neo4j_ok = await check_connectivity()
    if not neo4j_ok:
        raise HTTPException(
            status_code=503,
            detail="Neo4j is unavailable.",
        )

    return await service.find_similar_incidents(incident_id, limit)


# ---------------------------------------------------------------------------
# Record Applied Mitigation
# ---------------------------------------------------------------------------
@app.post(
    "/api/v1/memory/incidents/{incident_id}/mitigations",
    response_model=ApplyMitigationResponse,
)
async def apply_mitigation(
    incident_id: str,
    request: ApplyMitigationRequest,
):
    """
    Record an explicitly applied mitigation for an incident.

    Creates or links a Mitigation node through APPLIED relationship.
    Does not claim the mitigation succeeded.
    """
    service = get_service()

    neo4j_ok = await check_connectivity()
    if not neo4j_ok:
        raise HTTPException(
            status_code=503,
            detail="Neo4j is unavailable.",
        )

    try:
        return await service.apply_mitigation(
            incident_id=incident_id,
            idempotency_key=request.idempotency_key,
            description=request.description,
            applied_at=request.applied_at,
            recorded_by=request.recorded_by,
            notes=request.notes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


# ---------------------------------------------------------------------------
# Record Outcome
# ---------------------------------------------------------------------------
@app.post(
    "/api/v1/memory/incidents/{incident_id}/outcomes",
    response_model=RecordOutcomeResponse,
)
async def record_outcome(
    incident_id: str,
    request: RecordOutcomeRequest,
):
    """
    Record an explicit outcome observation for an incident.

    If a mitigation application is referenced, creates a temporal
    FOLLOWED_BY relationship without encoding a causal claim.
    """
    service = get_service()

    neo4j_ok = await check_connectivity()
    if not neo4j_ok:
        raise HTTPException(
            status_code=503,
            detail="Neo4j is unavailable.",
        )

    try:
        return await service.record_outcome(
            incident_id=incident_id,
            idempotency_key=request.idempotency_key,
            status=request.status,
            description=request.description,
            observed_at=request.observed_at,
            recorded_by=request.recorded_by,
            mitigation_application_id=request.mitigation_application_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
