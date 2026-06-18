"""
FastAPI Application -- Phase 9 Evaluation API
===============================================
Exposes evaluation, batch, label, and lookup endpoints.

Start with:
    PYTHONPATH=src uvicorn tars.phase9.api:app --host 0.0.0.0 --port 8006

API base path: /api/v1/evaluations

Phase 9 is analysis-only. It never calls flight-control APIs,
invokes Gemini, or mutates upstream records.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .database import check_database, close_engine, get_session
from .evaluator import Evaluator
from .ground_truth import GroundTruthLoader
from .models import (
    BatchEvaluationRequest,
    BatchEvaluationResponse,
    EvaluationListResponse,
    EvaluationRequest,
    EvaluationResponse,
    GroundTruthLabelCreate,
    GroundTruthLabelResponse,
    HealthResponse,
    ReasoningEvaluationListResponse,
)
from .phoenix_exporter import PhoenixEvalExporter
from .repository import EvaluationRepository
from .service import EvaluationService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("phase9.api")

# ---------------------------------------------------------------------------
# Application state
# ---------------------------------------------------------------------------
_phase4_client: Optional[object] = None
_phase5_client: Optional[object] = None
_phase7_client: Optional[object] = None
_phoenix_exporter: Optional[PhoenixEvalExporter] = None


def _create_service(session: AsyncSession) -> EvaluationService:
    """Create an EvaluationService with the given session."""
    repository = EvaluationRepository(session)
    ground_truth_loader = GroundTruthLoader(
        repository=repository,
        phase7_client=_phase7_client,
    )
    return EvaluationService(
        repository=repository,
        ground_truth_loader=ground_truth_loader,
        evaluator=Evaluator(),
        phoenix_exporter=_phoenix_exporter or PhoenixEvalExporter(),
        phase4_client=_phase4_client,
        phase5_client=_phase5_client,
    )


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage database connections and optional upstream clients."""
    global _phase4_client, _phase5_client, _phase7_client, _phoenix_exporter

    # Validate configuration
    try:
        settings.validate_weights()
    except ValueError as exc:
        logger.error("Configuration validation failed: %s", exc)
        raise

    # Initialize optional upstream clients
    try:
        from .adapters.phase4_client import Phase4Client
        _phase4_client = Phase4Client()
        logger.info("Phase 4 client initialized: %s", settings.PHASE4_API_URL)
    except Exception as exc:
        logger.warning("Phase 4 client unavailable: %s", exc)

    try:
        from .adapters.phase5_client import Phase5Client
        _phase5_client = Phase5Client()
        logger.info("Phase 5 client initialized: %s", settings.PHASE5_API_URL)
    except Exception as exc:
        logger.warning("Phase 5 client unavailable: %s", exc)

    try:
        from .adapters.phase7_client import Phase7Client
        _phase7_client = Phase7Client()
        logger.info("Phase 7 client initialized: %s", settings.PHASE7_API_URL)
    except Exception as exc:
        logger.warning("Phase 7 client unavailable: %s", exc)

    # Initialize Phoenix exporter
    _phoenix_exporter = PhoenixEvalExporter()

    logger.info("Phase 9 Evaluation API started")
    logger.info("Database: %s", settings.EVALUATION_DATABASE_URL)
    logger.info("Evaluator version: %s", settings.EVALUATION_VERSION)
    logger.info("Phoenix export: %s", settings.EVALUATION_EXPORT_PHOENIX)

    yield

    # Shutdown
    await close_engine()
    logger.info("Phase 9 Evaluation API stopped")


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------
app = FastAPI(
    title="TARS Phase 9 -- Evaluation API",
    description=(
        "Measures the quality of reasoning outputs against bounded "
        "ground-truth labels, mission outcomes, and incident facts."
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
    if not settings.EVALUATION_ENABLED:
        return HealthResponse(
            status="disabled",
            postgres="disabled",
        )

    pg_ok = await check_database()

    phase4_status = "unknown"
    if _phase4_client is not None and hasattr(_phase4_client, "health_check"):
        phase4_status = "ok" if await _phase4_client.health_check() else "unavailable"

    phase5_status = "unknown"
    if _phase5_client is not None and hasattr(_phase5_client, "health_check"):
        phase5_status = "ok" if await _phase5_client.health_check() else "unavailable"

    phase7_status = "disabled"
    if _phase7_client is not None and hasattr(_phase7_client, "health_check"):
        try:
            phase7_status = "ok" if await _phase7_client.health_check() else "unavailable"
        except Exception:
            phase7_status = "unavailable"

    phoenix_status = "disabled"
    if settings.EVALUATION_EXPORT_PHOENIX:
        phoenix_status = "enabled"

    return HealthResponse(
        status="ok" if pg_ok else "degraded",
        postgres="ok" if pg_ok else "unavailable",
        phase4=phase4_status,
        phase5=phase5_status,
        phase7=phase7_status,
        phoenix=phoenix_status,
    )


# ---------------------------------------------------------------------------
# Evaluate
# ---------------------------------------------------------------------------
@app.post(
    "/api/v1/evaluations/evaluate",
    response_model=EvaluationResponse,
)
async def evaluate(
    request: EvaluationRequest,
    session: AsyncSession = Depends(get_session),
):
    """
    Evaluate one reasoning result or mission-level target.

    Returns an evaluation result with bounded metrics and explanations.
    """
    if not settings.EVALUATION_ENABLED:
        raise HTTPException(
            status_code=503,
            detail="Evaluation service is disabled.",
        )

    service = _create_service(session)

    try:
        return await service.evaluate(request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:
        logger.error("Evaluation failed: %s", exc)
        raise HTTPException(
            status_code=500,
            detail="Internal evaluation error.",
        )


# ---------------------------------------------------------------------------
# Batch Evaluate
# ---------------------------------------------------------------------------
@app.post(
    "/api/v1/evaluations/batch",
    response_model=BatchEvaluationResponse,
)
async def evaluate_batch(
    request: BatchEvaluationRequest,
    session: AsyncSession = Depends(get_session),
):
    """
    Evaluate a bounded list of targets.

    Partial failures are returned per item. A failed item does not
    abort successful evaluations.
    """
    if not settings.EVALUATION_ENABLED:
        raise HTTPException(
            status_code=503,
            detail="Evaluation service is disabled.",
        )

    service = _create_service(session)

    try:
        return await service.evaluate_batch(request.targets)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.error("Batch evaluation failed: %s", exc)
        raise HTTPException(
            status_code=500,
            detail="Internal evaluation error.",
        )


# ---------------------------------------------------------------------------
# Get Evaluation
# ---------------------------------------------------------------------------
@app.get(
    "/api/v1/evaluations/{evaluation_id}",
    response_model=EvaluationResponse,
)
async def get_evaluation(
    evaluation_id: str,
    session: AsyncSession = Depends(get_session),
):
    """Return a stored evaluation result."""
    repository = EvaluationRepository(session)
    result = await repository.get_evaluation(evaluation_id)

    if result is None:
        raise HTTPException(
            status_code=404,
            detail=f"Evaluation '{evaluation_id}' not found.",
        )

    return result


# ---------------------------------------------------------------------------
# Get Evaluations by Mission
# ---------------------------------------------------------------------------
@app.get(
    "/api/v1/evaluations/mission/{mission_id}",
    response_model=EvaluationListResponse,
)
async def get_evaluations_by_mission(
    mission_id: str,
    session: AsyncSession = Depends(get_session),
):
    """Return all evaluations for a mission."""
    repository = EvaluationRepository(session)
    evaluations = await repository.get_evaluations_by_mission(mission_id)

    return EvaluationListResponse(
        mission_id=mission_id,
        evaluations=evaluations,
        total=len(evaluations),
    )


# ---------------------------------------------------------------------------
# Get Evaluations by Reasoning
# ---------------------------------------------------------------------------
@app.get(
    "/api/v1/evaluations/reasoning/{reasoning_id}",
    response_model=ReasoningEvaluationListResponse,
)
async def get_evaluations_by_reasoning(
    reasoning_id: str,
    session: AsyncSession = Depends(get_session),
):
    """Return all evaluations for a reasoning result."""
    repository = EvaluationRepository(session)
    evaluations = await repository.get_evaluations_by_reasoning(reasoning_id)

    return ReasoningEvaluationListResponse(
        reasoning_id=reasoning_id,
        evaluations=evaluations,
        total=len(evaluations),
    )


# ---------------------------------------------------------------------------
# Labels
# ---------------------------------------------------------------------------
@app.post(
    "/api/v1/evaluations/labels",
    response_model=GroundTruthLabelResponse,
)
async def create_label(
    request: GroundTruthLabelCreate,
    session: AsyncSession = Depends(get_session),
):
    """
    Create or update an explicit ground-truth label.

    Useful for tests and operator-reviewed workflows.
    """
    if not settings.EVALUATION_ENABLED:
        raise HTTPException(
            status_code=503,
            detail="Evaluation service is disabled.",
        )

    repository = EvaluationRepository(session)

    try:
        return await repository.upsert_label(
            mission_id=request.mission_id,
            incident_id=request.incident_id,
            root_cause=request.root_cause,
            preferred_mitigation=request.preferred_mitigation,
            outcome=request.outcome,
            source=request.source.value,
            labeled_by=request.labeled_by,
            labeled_at=request.labeled_at,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.error("Label creation failed: %s", exc)
        raise HTTPException(
            status_code=500,
            detail="Internal error creating label.",
        )
