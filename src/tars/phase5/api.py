"""
FastAPI Application -- Phase 5 Reasoning API
=============================================
Exposes reasoning analysis and querying endpoints.

Start with:
    PYTHONPATH=src uvicorn tars.phase5.api:app --host 0.0.0.0 --port 8004

API base path: /api/v1
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Optional

import httpx
from fastapi import FastAPI, HTTPException

from .config import settings
from .incident_client import IncidentClient
from .models import (
    AnalyzeRequest,
    AnalyzeResponse,
    HealthResponse,
    ReasoningListResponse,
    ReasoningResult,
)
from .service import ReasoningService
from .store import ReasoningStore

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("phase5.api")

# ---------------------------------------------------------------------------
# Application state (initialized on startup)
# ---------------------------------------------------------------------------
_store: Optional[ReasoningStore] = None
_service: Optional[ReasoningService] = None
_incident_client: Optional[IncidentClient] = None
_provider: Optional[object] = None


def get_service() -> ReasoningService:
    """Get the ReasoningService instance."""
    if _service is None:
        raise RuntimeError("ReasoningService not initialized")
    return _service


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage Redis connection and provider lifecycle."""
    global _store, _service, _incident_client, _provider

    _store = ReasoningStore()
    await _store.connect()

    _incident_client = IncidentClient()

    # Try to create the Gemini provider; fall back gracefully
    try:
        from .agent import create_reasoning_agent
        from .provider import GeminiReasoningProvider

        if settings.GEMINI_API_KEY:
            agent = create_reasoning_agent()
            _provider = GeminiReasoningProvider(agent)
            logger.info("Gemini provider configured: %s", settings.GEMINI_MODEL)
        else:
            logger.warning(
                "GEMINI_API_KEY not set; Gemini provider unconfigured. "
                "Analysis endpoints will return configuration errors."
            )
            _provider = _create_unconfigured_provider()
    except ImportError as exc:
        logger.warning(
            "Google ADK not available: %s. "
            "Using unconfigured provider stub.",
            exc,
        )
        _provider = _create_unconfigured_provider()

    _service = ReasoningService(
        store=_store,
        incident_client=_incident_client,
        provider=_provider,
    )

    logger.info("Phase 5 Reasoning API started")
    logger.info("Redis: %s", settings.REDIS_URL)
    logger.info("Phase 4 API: %s", settings.PHASE4_API_URL)

    yield

    if _store is not None:
        await _store.close()
    logger.info("Phase 5 Reasoning API stopped")


def _create_unconfigured_provider():
    """Create a provider stub that reports unconfigured status."""
    from .provider import FakeReasoningProvider

    return FakeReasoningProvider(
        model_name="unconfigured",
        configured=False,
    )


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------
app = FastAPI(
    title="TARS Phase 5 -- Gemini Reasoning API",
    description=(
        "Advisory root-cause analysis of Phase 4 incidents "
        "using Gemini reasoning."
    ),
    version="0.1.0",
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------
@app.get("/health", response_model=HealthResponse)
async def health():
    """Return API, Redis, Phase 4, and Gemini readiness."""
    redis_ok = False
    if _store is not None:
        redis_ok = await _store.ping()

    phase4_ok = False
    if _incident_client is not None:
        phase4_ok = await _incident_client.health_check()

    gemini_status = "unconfigured"
    if _provider is not None and hasattr(_provider, "is_configured"):
        if _provider.is_configured():
            gemini_status = "ok"

    return HealthResponse(
        status="ok",
        redis="ok" if redis_ok else "unavailable",
        phase4="ok" if phase4_ok else "unavailable",
        gemini=gemini_status,
    )


# ---------------------------------------------------------------------------
# Analyze Incident
# ---------------------------------------------------------------------------
@app.post(
    "/api/v1/reasoning/analyze/{mission_id}/{incident_id}",
    response_model=AnalyzeResponse,
)
async def analyze_incident(
    mission_id: str,
    incident_id: str,
    request: AnalyzeRequest = AnalyzeRequest(),
):
    """
    Analyze a Phase 4 incident through the Gemini reasoning provider.

    Fetches the incident from Phase 4, invokes reasoning, validates
    the output, and persists the result.

    When overwrite=false, returns a cached analysis if one exists,
    even if the Gemini provider is unconfigured.
    """
    service = get_service()

    # When overwrite=false, try to return a cached analysis first.
    # This must happen before the provider configuration check so
    # cached results are accessible even without Gemini credentials.
    if not request.overwrite:
        existing = await service.get_analysis(mission_id, incident_id)
        if existing is not None:
            return AnalyzeResponse(
                reasoning_id=existing.reasoning_id,
                mission_id=existing.mission_id,
                incident_id=existing.incident_id,
                incident_type=existing.incident_type,
                root_cause=existing.root_cause,
                confidence=existing.confidence,
                recommendation=existing.recommendation,
                rationale=existing.rationale,
                contributing_factors=existing.contributing_factors,
                uncertainties=existing.uncertainties,
                model=existing.model,
                prompt_version=existing.prompt_version,
                created_at=existing.created_at,
                advisory_only=existing.advisory_only,
            )

    # Check provider configuration only when we need to invoke Gemini
    if _provider is not None and hasattr(_provider, "is_configured"):
        if not _provider.is_configured():
            raise HTTPException(
                status_code=503,
                detail=(
                    "Gemini reasoning provider is not configured. "
                    "Set GEMINI_API_KEY environment variable."
                ),
            )

    try:
        result = await service.analyze_incident(
            mission_id=mission_id,
            incident_id=incident_id,
            overwrite=request.overwrite,
        )
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            raise HTTPException(
                status_code=404,
                detail=(
                    f"Incident '{incident_id}' not found "
                    f"for mission '{mission_id}' in Phase 4"
                ),
            )
        raise HTTPException(
            status_code=502,
            detail=(
                f"Phase 4 API error: {exc.response.status_code}"
            ),
        )
    except httpx.ConnectError:
        raise HTTPException(
            status_code=502,
            detail="Phase 4 Incident API is unreachable",
        )
    except RuntimeError as exc:
        # Provider not configured
        raise HTTPException(
            status_code=503,
            detail=str(exc),
        )
    except ValueError as exc:
        # Malformed model output or identifier mismatch
        raise HTTPException(
            status_code=502,
            detail=f"Reasoning failed: {exc}",
        )
    except Exception as exc:
        logger.error(
            "Unexpected error analyzing incident '%s': %s",
            incident_id,
            exc,
        )
        raise HTTPException(
            status_code=500,
            detail="Internal reasoning error",
        )

    return AnalyzeResponse(
        reasoning_id=result.reasoning_id,
        mission_id=result.mission_id,
        incident_id=result.incident_id,
        incident_type=result.incident_type,
        root_cause=result.root_cause,
        confidence=result.confidence,
        recommendation=result.recommendation,
        rationale=result.rationale,
        contributing_factors=result.contributing_factors,
        uncertainties=result.uncertainties,
        model=result.model,
        prompt_version=result.prompt_version,
        created_at=result.created_at,
        advisory_only=result.advisory_only,
    )


# ---------------------------------------------------------------------------
# Get Incident Analysis
# ---------------------------------------------------------------------------
@app.get(
    "/api/v1/reasoning/{mission_id}/{incident_id}",
    response_model=ReasoningResult,
)
async def get_analysis(mission_id: str, incident_id: str):
    """Return the current persisted analysis for an incident."""
    service = get_service()
    result = await service.get_analysis(mission_id, incident_id)

    if result is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"No analysis found for incident '{incident_id}' "
                f"in mission '{mission_id}'"
            ),
        )

    return result


# ---------------------------------------------------------------------------
# List Mission Analyses
# ---------------------------------------------------------------------------
@app.get(
    "/api/v1/reasoning/{mission_id}",
    response_model=ReasoningListResponse,
)
async def list_analyses(mission_id: str):
    """Return all persisted incident analyses for a mission."""
    service = get_service()
    return await service.list_analyses(mission_id)
