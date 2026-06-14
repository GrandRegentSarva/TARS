"""
Reasoning Service
=================
Orchestrates incident retrieval, reasoning, validation, and persistence.

Service flow:
1. Check for existing analysis (if overwrite=false, return it).
2. Fetch the incident from Phase 4.
3. Invoke the reasoning provider.
4. Validate the structured response.
5. Persist and return the result.
6. On failure, do not persist.

Phase 6 tracing:
Each call to analyze_incident() creates a root ``reasoning.analyze`` span
with child spans for cache lookup, incident retrieval, prompt building,
Gemini invocation, validation, and persistence. Tracing is best-effort
and never changes return values or exception behavior.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from opentelemetry import trace
from opentelemetry.trace import StatusCode

from .config import settings
from .incident_client import IncidentClient
from .models import (
    ReasoningAnalysis,
    ReasoningListResponse,
    ReasoningResult,
)
from .prompts import PROMPT_VERSION
from .store import ReasoningStore

logger = logging.getLogger("phase5.service")


def _get_tracer() -> trace.Tracer:
    """Get the Phase 6 tracer, falling back to no-op if unavailable."""
    try:
        from tars.phase6.tracing import get_tracer
        return get_tracer()
    except ImportError:
        return trace.get_tracer("tars.phase5")


def _get_attributes():
    """Import Phase 6 attributes, returning None if unavailable."""
    try:
        from tars.phase6 import attributes as attrs
        return attrs
    except ImportError:
        return None


def _get_config():
    """Import Phase 6 config, returning None if unavailable."""
    try:
        from tars.phase6.config import phoenix_settings
        return phoenix_settings
    except ImportError:
        return None


class ReasoningService:
    """
    Orchestrates reasoning analysis for Phase 4 incidents.

    Coordinates between the incident client, reasoning provider,
    and Redis store.
    """

    def __init__(
        self,
        store: ReasoningStore,
        incident_client: IncidentClient,
        provider: Any,  # ReasoningProvider protocol
    ) -> None:
        self._store = store
        self._incident_client = incident_client
        self._provider = provider

    async def analyze_incident(
        self,
        mission_id: str,
        incident_id: str,
        overwrite: bool = True,
    ) -> ReasoningResult:
        """
        Analyze a Phase 4 incident through the reasoning provider.

        Args:
            mission_id: Mission identifier.
            incident_id: Incident identifier.
            overwrite: If False, return existing analysis without
                       invoking the provider.

        Returns:
            ReasoningResult with the analysis.

        Raises:
            Various exceptions propagated from client/provider/store.
        """
        tracer = _get_tracer()
        attrs = _get_attributes()
        cfg = _get_config()

        # Build initial root span attributes
        root_attrs = {}
        if attrs is not None:
            root_attrs = attrs.reasoning_attributes(
                mission_id=mission_id,
                incident_id=incident_id,
                overwrite=overwrite,
            )

        with tracer.start_as_current_span(
            "reasoning.analyze" if attrs is None else attrs.SPAN_REASONING_ANALYZE,
            attributes=root_attrs,
        ) as root_span:
            try:
                return await self._analyze_with_tracing(
                    mission_id=mission_id,
                    incident_id=incident_id,
                    overwrite=overwrite,
                    root_span=root_span,
                    tracer=tracer,
                    attrs=attrs,
                    cfg=cfg,
                )
            except Exception as exc:
                # Mark root span as error but re-raise original exception
                root_span.set_status(StatusCode.ERROR, str(exc))
                root_span.record_exception(exc)
                if attrs is not None:
                    root_span.set_attribute(
                        attrs.TARS_REASONING_OUTCOME,
                        attrs.OUTCOME_FAILED,
                    )
                raise

    async def _analyze_with_tracing(
        self,
        *,
        mission_id: str,
        incident_id: str,
        overwrite: bool,
        root_span: trace.Span,
        tracer: trace.Tracer,
        attrs: Any,
        cfg: Any,
    ) -> ReasoningResult:
        """
        Internal analysis with full span instrumentation.

        Separated from analyze_incident() to keep the try/except
        boundary clean.
        """
        # --- Cache Lookup ---
        if not overwrite:
            with tracer.start_as_current_span(
                "reasoning.cache_lookup"
                if attrs is None
                else attrs.SPAN_REASONING_CACHE_LOOKUP,
                attributes=(
                    {attrs.OI_OPENINFERENCE_SPAN_KIND: attrs.OI_SPAN_KIND_CHAIN}
                    if attrs is not None
                    else {}
                ),
            ) as cache_span:
                existing = await self._store.get_analysis(
                    mission_id, incident_id
                )
                if existing is not None:
                    cache_span.set_attribute("cache.hit", True)
                    if attrs is not None:
                        root_span.set_attribute(
                            attrs.TARS_REASONING_CACHED, True
                        )
                        root_span.set_attributes(
                            attrs.result_attributes(
                                reasoning_id=existing.reasoning_id,
                                root_cause=existing.root_cause,
                                confidence=existing.confidence,
                                prompt_version=existing.prompt_version,
                                cached=True,
                            )
                        )
                    logger.info(
                        "Returning existing analysis for incident '%s' "
                        "(overwrite=false)",
                        incident_id,
                    )
                    return existing
                cache_span.set_attribute("cache.hit", False)

        # --- Fetch Incident from Phase 4 ---
        with tracer.start_as_current_span(
            "phase4.get_incident"
            if attrs is None
            else attrs.SPAN_PHASE4_GET_INCIDENT,
            attributes=(
                {attrs.OI_OPENINFERENCE_SPAN_KIND: attrs.OI_SPAN_KIND_RETRIEVER}
                if attrs is not None
                else {}
            ),
        ) as incident_span:
            try:
                logger.info(
                    "Fetching incident '%s' from Phase 4 for mission '%s'",
                    incident_id,
                    mission_id,
                )
                incident = await self._incident_client.get_incident(
                    mission_id, incident_id
                )
                # Add incident details to root span
                inc_type = incident.get("incident_type", "unknown")
                inc_severity = incident.get("severity", "unknown")
                if attrs is not None:
                    root_span.set_attributes(
                        attrs.incident_attributes(
                            incident_type=inc_type,
                            severity=inc_severity,
                        )
                    )
                    incident_span.set_attribute(
                        attrs.TARS_INCIDENT_TYPE, inc_type
                    )
                    incident_span.set_attribute(
                        attrs.TARS_INCIDENT_SEVERITY, inc_severity
                    )
            except Exception as exc:
                incident_span.set_status(StatusCode.ERROR, str(exc))
                incident_span.record_exception(exc)
                raise

        # --- Build Prompt ---
        with tracer.start_as_current_span(
            "reasoning.build_prompt"
            if attrs is None
            else attrs.SPAN_REASONING_BUILD_PROMPT,
            attributes=(
                {attrs.OI_OPENINFERENCE_SPAN_KIND: attrs.OI_SPAN_KIND_CHAIN}
                if attrs is not None
                else {}
            ),
        ) as prompt_span:
            try:
                from .prompts import build_incident_prompt
                prompt_text = build_incident_prompt(incident)
                prompt_span.set_attribute("prompt.length", len(prompt_text))
            except Exception as exc:
                prompt_span.set_status(StatusCode.ERROR, str(exc))
                prompt_span.record_exception(exc)
                raise

        # --- Invoke Reasoning Provider ---
        logger.info(
            "Invoking reasoning provider for incident '%s'",
            incident_id,
        )
        analysis: ReasoningAnalysis = await self._provider.analyze(incident)

        # --- Validate and Build Result ---
        with tracer.start_as_current_span(
            "reasoning.validate"
            if attrs is None
            else attrs.SPAN_REASONING_VALIDATE,
            attributes=(
                {attrs.OI_OPENINFERENCE_SPAN_KIND: attrs.OI_SPAN_KIND_CHAIN}
                if attrs is not None
                else {}
            ),
        ) as validate_span:
            try:
                reasoning_id = f"reason_{uuid.uuid4().hex[:12]}"
                now = datetime.now(timezone.utc).isoformat()

                result = ReasoningResult(
                    reasoning_id=reasoning_id,
                    mission_id=mission_id,
                    incident_id=incident_id,
                    incident_type=incident.get("incident_type", "unknown"),
                    root_cause=analysis.root_cause,
                    confidence=analysis.confidence,
                    recommendation=analysis.recommendation,
                    rationale=analysis.rationale,
                    contributing_factors=analysis.contributing_factors,
                    uncertainties=analysis.uncertainties,
                    model=self._provider.model_name,
                    prompt_version=PROMPT_VERSION,
                    created_at=now,
                    advisory_only=True,
                )
                validate_span.set_attribute("validation.passed", True)
            except Exception as exc:
                validate_span.set_status(StatusCode.ERROR, str(exc))
                validate_span.record_exception(exc)
                validate_span.set_attribute("validation.passed", False)
                raise

        # --- Persist Result ---
        with tracer.start_as_current_span(
            "reasoning.persist"
            if attrs is None
            else attrs.SPAN_REASONING_PERSIST,
            attributes=(
                {attrs.OI_OPENINFERENCE_SPAN_KIND: attrs.OI_SPAN_KIND_CHAIN}
                if attrs is not None
                else {}
            ),
        ) as persist_span:
            try:
                await self._store.save_analysis(
                    mission_id, incident_id, result
                )
                persist_span.set_attribute("persistence.success", True)
            except Exception as exc:
                persist_span.set_status(StatusCode.ERROR, str(exc))
                persist_span.record_exception(exc)
                persist_span.set_attribute("persistence.success", False)
                raise

        # --- Set final result attributes on root span ---
        if attrs is not None:
            root_span.set_attributes(
                attrs.result_attributes(
                    reasoning_id=result.reasoning_id,
                    root_cause=result.root_cause,
                    confidence=result.confidence,
                    prompt_version=result.prompt_version,
                    cached=False,
                )
            )

        logger.info(
            "Analysis complete for incident '%s': root_cause='%s', "
            "confidence=%.2f",
            incident_id,
            result.root_cause,
            result.confidence,
        )

        return result

    async def get_analysis(
        self,
        mission_id: str,
        incident_id: str,
    ) -> Optional[ReasoningResult]:
        """Get the current persisted analysis for an incident."""
        return await self._store.get_analysis(mission_id, incident_id)

    async def list_analyses(
        self,
        mission_id: str,
    ) -> ReasoningListResponse:
        """List all persisted analyses for a mission."""
        analyses = await self._store.list_analyses(mission_id)
        return ReasoningListResponse(
            mission_id=mission_id,
            analyses=analyses,
            total=len(analyses),
        )
