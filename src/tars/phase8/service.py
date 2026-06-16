"""
Introspection Service
=====================
Orchestrates Phoenix MCP trace search, summarization, and comparison.

This service is the single entry point for Phase 5 reasoning to access
trace introspection. Phase 5 should depend only on this service interface
and must not construct Phoenix queries directly.

Service flow:
1. Check policy: is introspection allowed for this request?
2. Build search request from current incident context.
3. Query Phoenix through the trace client.
4. Summarize results through the summarizer.
5. Return bounded introspection context for the reasoning prompt.
6. On any failure, return empty introspection and continue.

Tracing:
All tool calls are recorded as child spans in Phase 6/Phoenix using
OpenTelemetry instrumentation.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from opentelemetry import trace
from opentelemetry.trace import StatusCode

from .config import PhoenixMCPSettings, mcp_settings
from .models import (
    IntrospectionContext,
    IntrospectionResult,
    TraceCompareRequest,
    TraceCompareResponse,
    TraceSearchRequest,
    TraceSearchResponse,
    TraceSummaryRequest,
    TraceSummaryResponse,
)
from .phoenix_client import FakePhoenixTraceClient, PhoenixTraceClient
from .summarizer import TraceSummarizer
from .tool_policy import IntrospectionPolicy

logger = logging.getLogger("phase8.service")


def _get_tracer() -> trace.Tracer:
    """Get the Phase 6 tracer, falling back to no-op if unavailable."""
    try:
        from tars.phase6.tracing import get_tracer
        return get_tracer()
    except ImportError:
        return trace.get_tracer("tars.phase8")


def _get_attributes():
    """Import Phase 6 attributes, returning None if unavailable."""
    try:
        from tars.phase6 import attributes as attrs
        return attrs
    except ImportError:
        return None


# Span names for Phase 8 operations
SPAN_INTROSPECTION_SEARCH = "introspection.search_traces"
SPAN_INTROSPECTION_SUMMARY = "introspection.get_trace_summary"
SPAN_INTROSPECTION_COMPARE = "introspection.compare_traces"
SPAN_INTROSPECTION_CONTEXT = "introspection.build_context"


class IntrospectionService:
    """
    Orchestrates Phoenix MCP trace introspection for Phase 5 reasoning.

    Provides three tool operations (search, summary, compare) and a
    high-level context builder for automatic introspection during
    reasoning.
    """

    def __init__(
        self,
        *,
        client: Optional[Any] = None,
        summarizer: Optional[TraceSummarizer] = None,
        policy: Optional[IntrospectionPolicy] = None,
        settings: Optional[PhoenixMCPSettings] = None,
    ) -> None:
        self._settings = settings or mcp_settings
        self._client = client or (
            PhoenixTraceClient(settings=self._settings)
            if self._settings.is_enabled
            else FakePhoenixTraceClient(unavailable=True)
        )
        self._summarizer = summarizer or TraceSummarizer(settings=self._settings)
        self._policy = policy or IntrospectionPolicy(settings=self._settings)

    # -----------------------------------------------------------------------
    # Tool Operations
    # -----------------------------------------------------------------------

    async def search_traces(
        self,
        request: TraceSearchRequest,
    ) -> TraceSearchResponse:
        """
        Search Phoenix for traces matching the given filters.

        Records the search as a child span in Phoenix.

        Args:
            request: Bounded search request.

        Returns:
            TraceSearchResponse with matching trace metadata.
        """
        tracer = _get_tracer()
        attrs = _get_attributes()

        span_attrs = {}
        if attrs is not None:
            span_attrs = {
                attrs.OI_OPENINFERENCE_SPAN_KIND: attrs.OI_SPAN_KIND_TOOL,
            }
            if request.mission_id:
                span_attrs[attrs.TARS_MISSION_ID] = request.mission_id
            if request.incident_id:
                span_attrs[attrs.TARS_INCIDENT_ID] = request.incident_id

        with tracer.start_as_current_span(
            SPAN_INTROSPECTION_SEARCH,
            attributes=span_attrs,
        ) as span:
            try:
                raw_traces = await self._client.search_traces(request)

                # Summarize each trace to safe metadata
                trace_metas = []
                for raw in raw_traces:
                    try:
                        meta = self._summarizer.summarize_trace_metadata(raw)
                        trace_metas.append(meta)
                    except Exception as exc:
                        logger.warning(
                            "Skipping malformed trace in search results: %s",
                            exc,
                        )

                total = len(trace_metas)
                truncated = total >= request.limit

                span.set_attribute("introspection.traces_found", total)
                span.set_attribute("introspection.truncated", truncated)

                return TraceSearchResponse(
                    traces=trace_metas,
                    total=total,
                    truncated=truncated,
                )

            except Exception as exc:
                span.set_status(StatusCode.ERROR, str(exc))
                span.record_exception(exc)
                logger.warning(
                    "Trace search failed (continuing without traces): %s",
                    exc,
                )
                return TraceSearchResponse()

    async def get_trace_summary(
        self,
        request: TraceSummaryRequest,
    ) -> Optional[TraceSummaryResponse]:
        """
        Get a safe summary for a single trace.

        Args:
            request: Request with trace ID.

        Returns:
            TraceSummaryResponse or None if trace not found.
        """
        tracer = _get_tracer()
        attrs = _get_attributes()

        span_attrs = {}
        if attrs is not None:
            span_attrs = {
                attrs.OI_OPENINFERENCE_SPAN_KIND: attrs.OI_SPAN_KIND_TOOL,
            }

        with tracer.start_as_current_span(
            SPAN_INTROSPECTION_SUMMARY,
            attributes=span_attrs,
        ) as span:
            try:
                span.set_attribute("introspection.trace_id", request.trace_id)

                raw_trace = await self._client.get_trace(request.trace_id)
                if raw_trace is None:
                    span.set_attribute("introspection.trace_found", False)
                    return None

                summary = self._summarizer.summarize_trace(raw_trace)
                span.set_attribute("introspection.trace_found", True)
                span.set_attribute(
                    "introspection.stages_count", len(summary.stages)
                )

                return TraceSummaryResponse(
                    trace_id=summary.trace_id,
                    reasoning_id=summary.reasoning_id,
                    root_span=summary.root_span,
                    stages=summary.stages,
                    prompt_version=summary.prompt_version,
                    model=summary.model,
                    captured_content=summary.captured_content,
                    summary=summary.summary,
                    truncated=summary.truncated,
                )

            except Exception as exc:
                span.set_status(StatusCode.ERROR, str(exc))
                span.record_exception(exc)
                logger.warning(
                    "Trace summary failed for '%s' "
                    "(continuing without summary): %s",
                    request.trace_id,
                    exc,
                )
                return None

    async def compare_traces(
        self,
        request: TraceCompareRequest,
    ) -> TraceCompareResponse:
        """
        Compare a set of traces and summarize patterns.

        The comparison is descriptive only. It never returns accuracy
        scores, success rates, or validated lessons.

        Args:
            request: Request with trace IDs.

        Returns:
            TraceCompareResponse with observed patterns.
        """
        tracer = _get_tracer()
        attrs = _get_attributes()

        span_attrs = {}
        if attrs is not None:
            span_attrs = {
                attrs.OI_OPENINFERENCE_SPAN_KIND: attrs.OI_SPAN_KIND_TOOL,
            }

        with tracer.start_as_current_span(
            SPAN_INTROSPECTION_COMPARE,
            attributes=span_attrs,
        ) as span:
            try:
                span.set_attribute(
                    "introspection.compare_count", len(request.trace_ids)
                )

                # Fetch all traces
                raw_traces = await self._client.get_traces_by_ids(
                    request.trace_ids
                )

                # Summarize each
                summaries = []
                for raw in raw_traces:
                    try:
                        summary = self._summarizer.summarize_trace(raw)
                        summaries.append(summary)
                    except Exception as exc:
                        logger.warning(
                            "Skipping malformed trace in comparison: %s", exc
                        )

                # Compare
                result = self._summarizer.compare_traces(summaries)

                span.set_attribute(
                    "introspection.compared_count", len(summaries)
                )

                return result

            except Exception as exc:
                span.set_status(StatusCode.ERROR, str(exc))
                span.record_exception(exc)
                logger.warning(
                    "Trace comparison failed "
                    "(continuing without comparison): %s",
                    exc,
                )
                return TraceCompareResponse(
                    trace_ids=request.trace_ids,
                    not_an_evaluation=True,
                )

    # -----------------------------------------------------------------------
    # High-Level Introspection for Phase 5
    # -----------------------------------------------------------------------

    async def build_introspection_context(
        self,
        *,
        mission_id: str,
        incident_id: str,
        incident_type: Optional[str] = None,
        use_introspection: bool = False,
    ) -> tuple[Optional[IntrospectionContext], IntrospectionResult]:
        """
        Build bounded introspection context for Phase 5 reasoning.

        This is the main entry point for Phase 5 integration. It:
        1. Checks the introspection policy.
        2. Searches for relevant prior traces.
        3. Builds a bounded context for the reasoning prompt.
        4. Returns safe provenance metadata for the result.

        On any failure, returns empty context and continues.

        Args:
            mission_id: Current mission identifier.
            incident_id: Current incident identifier.
            incident_type: Current incident type (optional filter).
            use_introspection: Whether introspection was requested.

        Returns:
            Tuple of (IntrospectionContext or None, IntrospectionResult).
        """
        # Default empty result
        empty_result = IntrospectionResult(introspection_used=False)

        # Check policy
        if not self._policy.should_introspect(
            use_introspection=use_introspection
        ):
            return None, empty_result

        tracer = _get_tracer()
        attrs = _get_attributes()

        span_attrs = {}
        if attrs is not None:
            span_attrs = {
                attrs.OI_OPENINFERENCE_SPAN_KIND: attrs.OI_SPAN_KIND_TOOL,
                attrs.TARS_MISSION_ID: mission_id,
                attrs.TARS_INCIDENT_ID: incident_id,
            }

        with tracer.start_as_current_span(
            SPAN_INTROSPECTION_CONTEXT,
            attributes=span_attrs,
        ) as span:
            try:
                # Search for relevant prior traces
                search_request = TraceSearchRequest(
                    incident_type=incident_type,
                    limit=self._policy.max_traces,
                )

                search_response = await self.search_traces(search_request)

                if not search_response.traces:
                    span.set_attribute("introspection.traces_found", 0)
                    logger.info(
                        "No prior traces found for introspection "
                        "(incident_type=%s)",
                        incident_type,
                    )
                    return None, IntrospectionResult(
                        introspection_used=True,
                        introspection_summary=(
                            "No prior traces found for this incident type."
                        ),
                    )

                # Build summary statements
                trace_ids = [t.trace_id for t in search_response.traces]
                summary_statements = self._build_summary_statements(
                    search_response
                )

                span.set_attribute(
                    "introspection.traces_consulted",
                    len(trace_ids),
                )

                context = IntrospectionContext(
                    source="phoenix_mcp",
                    traces_consulted=trace_ids,
                    summary=summary_statements,
                    limitations=[
                        "Trace history is descriptive and not an evaluation.",
                        "No accuracy labels are available in Phase 8.",
                    ],
                )

                result = IntrospectionResult(
                    introspection_used=True,
                    introspection_trace_ids=trace_ids,
                    introspection_summary=(
                        " ".join(summary_statements[:3])
                        if summary_statements
                        else "Prior traces consulted but no patterns identified."
                    ),
                )

                return context, result

            except Exception as exc:
                span.set_status(StatusCode.ERROR, str(exc))
                span.record_exception(exc)
                logger.warning(
                    "Introspection context build failed "
                    "(continuing without introspection): %s",
                    exc,
                )
                return None, IntrospectionResult(
                    introspection_used=True,
                    introspection_summary=(
                        "Introspection failed; reasoning continues "
                        "without prior trace context."
                    ),
                )

    # -----------------------------------------------------------------------
    # Health
    # -----------------------------------------------------------------------

    async def health_check(self) -> str:
        """
        Return the Phoenix MCP health status.

        Returns:
            'ok', 'disabled', or 'unavailable'.
        """
        if not self._settings.is_enabled:
            return "disabled"

        try:
            reachable = await self._client.health_check()
            return "ok" if reachable else "unavailable"
        except Exception:
            return "unavailable"

    async def close(self) -> None:
        """Close any open client connections."""
        try:
            await self._client.close()
        except Exception as exc:
            logger.warning("Error closing Phoenix client: %s", exc)

    # -----------------------------------------------------------------------
    # Internal Helpers
    # -----------------------------------------------------------------------

    def _build_summary_statements(
        self,
        search_response: TraceSearchResponse,
    ) -> list[str]:
        """Build bounded summary statements from search results."""
        statements: list[str] = []
        traces = search_response.traces

        if not traces:
            return statements

        # Count by incident type
        type_counts: dict[str, int] = {}
        for t in traces:
            if t.incident_type:
                type_counts[t.incident_type] = (
                    type_counts.get(t.incident_type, 0) + 1
                )

        for itype, count in type_counts.items():
            statements.append(
                f"{count} prior trace(s) involved {itype} incidents."
            )

        # Count by root cause
        cause_counts: dict[str, int] = {}
        for t in traces:
            if t.root_cause:
                cause_counts[t.root_cause] = (
                    cause_counts.get(t.root_cause, 0) + 1
                )

        for cause, count in cause_counts.items():
            statements.append(
                f"{count} prior trace(s) proposed {cause} as root cause."
            )

        # Count by outcome
        outcome_counts: dict[str, int] = {}
        for t in traces:
            if t.outcome:
                outcome_counts[t.outcome] = (
                    outcome_counts.get(t.outcome, 0) + 1
                )

        for outcome, count in outcome_counts.items():
            statements.append(
                f"{count} prior trace(s) had outcome: {outcome}."
            )

        # Prompt version info
        versions = {t.prompt_version for t in traces if t.prompt_version}
        if versions:
            statements.append(
                f"Prior traces used prompt version(s): "
                f"{', '.join(sorted(versions))}."
            )

        # Confidence range
        confidences = [
            t.confidence for t in traces if t.confidence is not None
        ]
        if confidences:
            statements.append(
                f"Prior confidence range: "
                f"{min(confidences):.2f} to {max(confidences):.2f}."
            )

        return statements[:10]  # Cap at 10 statements
