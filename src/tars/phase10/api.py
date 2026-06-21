"""
FastAPI Application -- Phase 10 Learning API
===============================================
Exposes learning run, candidate lookup, evidence, and retire endpoints.

Start with:
    PYTHONPATH=src uvicorn tars.phase10.api:app --host 0.0.0.0 --port 8007

API base path: /api/v1/learning

Phase 10 is analysis-only. It never calls flight-control APIs,
invokes Gemini, promotes validated knowledge, or mutates upstream records.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .database import check_database, close_engine, get_session
from .evidence_loader import EvidenceLoader
from .models import (
    CandidateListResponse,
    CandidateResponse,
    EvidenceListResponse,
    HealthResponse,
    LearningRunRequest,
    LearningRunResponse,
    RetireRequest,
)
from .pattern_miner import PatternMiner
from .repository import LearningRepository
from .scorer import CandidateScorer
from .service import LearningService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("phase10.api")

# ---------------------------------------------------------------------------
# Application state
# ---------------------------------------------------------------------------
_phase9_client: Optional[object] = None
_phase7_client: Optional[object] = None
_phoenix_client: Optional[object] = None


def _create_service(session: AsyncSession) -> LearningService:
    """Create a LearningService with the given session."""
    repository = LearningRepository(session)
    evidence_loader = EvidenceLoader(
        phase9_client=_phase9_client,
        phase7_client=_phase7_client,
        phoenix_client=_phoenix_client,
    )
    return LearningService(
        repository=repository,
        evidence_loader=evidence_loader,
        pattern_miner=PatternMiner(),
        scorer=CandidateScorer(),
    )


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage database connections and optional upstream clients."""
    global _phase9_client, _phase7_client, _phoenix_client

    # Validate configuration
    try:
        settings.validate()
    except ValueError as exc:
        logger.error("Configuration validation failed: %s", exc)
        raise

    # Initialize Phase 9 client (required)
    try:
        from .adapters.phase9_client import Phase9Client
        _phase9_client = Phase9Client()
        logger.info("Phase 9 client initialized: %s", settings.PHASE9_API_URL)
    except Exception as exc:
        logger.warning("Phase 9 client unavailable: %s", exc)

    # Initialize Phase 7 client (optional)
    try:
        from .adapters.phase7_client import Phase7Client
        _phase7_client = Phase7Client()
        logger.info("Phase 7 client initialized: %s", settings.PHASE7_API_URL)
    except Exception as exc:
        logger.warning("Phase 7 client unavailable: %s", exc)

    # Initialize Phoenix client (optional)
    if settings.LEARNING_TRACE_METADATA_ENABLED:
        try:
            from .adapters.phoenix_client import PhoenixClient
            _phoenix_client = PhoenixClient()
            logger.info(
                "Phoenix client initialized: %s", settings.PHOENIX_BASE_URL
            )
        except Exception as exc:
            logger.warning("Phoenix client unavailable: %s", exc)

    logger.info("Phase 10 Learning API started")
    logger.info("Database: %s", settings.LEARNING_DATABASE_URL)
    logger.info("Learning version: %s", settings.LEARNING_VERSION)
    logger.info(
        "Trace metadata: %s", settings.LEARNING_TRACE_METADATA_ENABLED
    )

    yield

    # Shutdown
    await close_engine()
    logger.info("Phase 10 Learning API stopped")


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------
app = FastAPI(
    title="TARS Phase 10 -- Learning API",
    description=(
        "Turns evaluated mission history into candidate operational "
        "knowledge. Candidate knowledge is not truth; it is a structured "
        "hypothesis backed by auditable evidence."
    ),
    version="0.1.0",
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------
@app.get("/health", response_model=HealthResponse)
async def health():
    """Return API, PostgreSQL, and optional dependency readiness."""
    if not settings.LEARNING_ENABLED:
        return HealthResponse(
            status="disabled",
            postgres="disabled",
            learning_version=settings.LEARNING_VERSION,
        )

    pg_ok = await check_database()

    phase9_status = "unknown"
    if _phase9_client is not None and hasattr(_phase9_client, "health_check"):
        try:
            phase9_status = (
                "ok" if await _phase9_client.health_check() else "unavailable"
            )
        except Exception:
            phase9_status = "unavailable"

    phase7_status = "disabled"
    if _phase7_client is not None and hasattr(_phase7_client, "health_check"):
        try:
            phase7_status = (
                "ok" if await _phase7_client.health_check() else "unavailable"
            )
        except Exception:
            phase7_status = "unavailable"

    phoenix_status = "disabled"
    if settings.LEARNING_TRACE_METADATA_ENABLED:
        if _phoenix_client is not None and hasattr(
            _phoenix_client, "health_check"
        ):
            try:
                phoenix_status = (
                    "ok"
                    if await _phoenix_client.health_check()
                    else "unavailable"
                )
            except Exception:
                phoenix_status = "unavailable"
        else:
            phoenix_status = "enabled"

    return HealthResponse(
        status="ok" if pg_ok else "degraded",
        postgres="ok" if pg_ok else "unavailable",
        phase9=phase9_status,
        phase7=phase7_status,
        phoenix=phoenix_status,
        learning_version=settings.LEARNING_VERSION,
    )


# ---------------------------------------------------------------------------
# Run Learning
# ---------------------------------------------------------------------------
@app.post(
    "/api/v1/learning/runs",
    response_model=LearningRunResponse,
)
async def run_learning(
    request: LearningRunRequest,
    session: AsyncSession = Depends(get_session),
):
    """
    Start a bounded learning run.

    Aggregates Phase 9 evaluation records into candidate knowledge.
    Use dry_run=true to preview candidates without persistence.
    """
    if not settings.LEARNING_ENABLED:
        raise HTTPException(
            status_code=503,
            detail="Learning service is disabled.",
        )

    service = _create_service(session)

    try:
        return await service.run_learning(request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:
        logger.error("Learning run failed: %s", exc)
        raise HTTPException(
            status_code=500,
            detail="Internal learning error.",
        )


# ---------------------------------------------------------------------------
# Get Run
# ---------------------------------------------------------------------------
@app.get(
    "/api/v1/learning/runs/{run_id}",
    response_model=LearningRunResponse,
)
async def get_run(
    run_id: str,
    session: AsyncSession = Depends(get_session),
):
    """Fetch a learning run status and summary."""
    if not settings.LEARNING_ENABLED:
        raise HTTPException(
            status_code=503,
            detail="Learning service is disabled.",
        )

    repository = LearningRepository(session)
    result = await repository.get_run(run_id)

    if result is None:
        raise HTTPException(
            status_code=404,
            detail=f"Learning run '{run_id}' not found.",
        )

    return result


# ---------------------------------------------------------------------------
# List Candidates
# ---------------------------------------------------------------------------
@app.get(
    "/api/v1/learning/candidates",
    response_model=CandidateListResponse,
)
async def list_candidates(
    candidate_type: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    incident_family: Optional[str] = Query(default=None),
    root_cause: Optional[str] = Query(default=None),
    min_confidence: Optional[float] = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(
        default=50,
        ge=1,
        le=100,
    ),
    session: AsyncSession = Depends(get_session),
):
    """List candidate knowledge with optional filters and pagination."""
    if not settings.LEARNING_ENABLED:
        raise HTTPException(
            status_code=503,
            detail="Learning service is disabled.",
        )

    repository = LearningRepository(session)
    candidates, total = await repository.list_candidates(
        candidate_type=candidate_type,
        status=status,
        incident_family=incident_family,
        root_cause=root_cause,
        min_confidence=min_confidence,
        page=page,
        page_size=page_size,
    )

    return CandidateListResponse(
        candidates=candidates,
        total=total,
        page=page,
        page_size=page_size,
    )


# ---------------------------------------------------------------------------
# Get Candidate
# ---------------------------------------------------------------------------
@app.get(
    "/api/v1/learning/candidates/{candidate_id}",
    response_model=CandidateResponse,
)
async def get_candidate(
    candidate_id: str,
    session: AsyncSession = Depends(get_session),
):
    """Fetch one candidate with evidence summary."""
    if not settings.LEARNING_ENABLED:
        raise HTTPException(
            status_code=503,
            detail="Learning service is disabled.",
        )

    repository = LearningRepository(session)
    result = await repository.get_candidate(candidate_id)

    if result is None:
        raise HTTPException(
            status_code=404,
            detail=f"Candidate '{candidate_id}' not found.",
        )

    return result


# ---------------------------------------------------------------------------
# Get Candidate Evidence
# ---------------------------------------------------------------------------
@app.get(
    "/api/v1/learning/candidates/{candidate_id}/evidence",
    response_model=EvidenceListResponse,
)
async def get_candidate_evidence(
    candidate_id: str,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(
        default=50,
        ge=1,
        le=100,
    ),
    session: AsyncSession = Depends(get_session),
):
    """Fetch bounded evidence items for a candidate."""
    if not settings.LEARNING_ENABLED:
        raise HTTPException(
            status_code=503,
            detail="Learning service is disabled.",
        )

    repository = LearningRepository(session)

    # Verify candidate exists
    candidate = await repository.get_candidate(candidate_id)
    if candidate is None:
        raise HTTPException(
            status_code=404,
            detail=f"Candidate '{candidate_id}' not found.",
        )

    evidence, total = await repository.get_evidence(
        candidate_id=candidate_id,
        page=page,
        page_size=page_size,
    )

    return EvidenceListResponse(
        candidate_id=candidate_id,
        evidence=evidence,
        total=total,
        page=page,
        page_size=page_size,
    )


# ---------------------------------------------------------------------------
# Retire Candidate
# ---------------------------------------------------------------------------
@app.post(
    "/api/v1/learning/candidates/{candidate_id}/retire",
    response_model=CandidateResponse,
)
async def retire_candidate(
    candidate_id: str,
    request: RetireRequest,
    session: AsyncSession = Depends(get_session),
):
    """Retire a candidate with a reason."""
    if not settings.LEARNING_ENABLED:
        raise HTTPException(
            status_code=503,
            detail="Learning service is disabled.",
        )

    repository = LearningRepository(session)

    retired = await repository.retire_candidate(
        candidate_id=candidate_id,
        reason=request.reason,
    )

    if not retired:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Candidate '{candidate_id}' not found or "
                f"not in 'proposed' status."
            ),
        )

    # Return updated candidate
    result = await repository.get_candidate(candidate_id)
    if result is None:
        raise HTTPException(
            status_code=404,
            detail=f"Candidate '{candidate_id}' not found after retire.",
        )

    return result
