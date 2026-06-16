"""
Trace Summarizer
================
Converts raw Phoenix trace/span data into safe, compact summaries
suitable for introspection.

Safety guarantees:
- Redacts secret-like fields (API keys, credentials, URLs with auth).
- Truncates prompt/response snippets according to content mode.
- Drops unsafe span attributes.
- Preserves mission, incident, reasoning, model, prompt version, and status.
- Never returns raw telemetry, replay frames, or full stack traces.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Optional

from .config import MCPContentMode, PhoenixMCPSettings, mcp_settings
from .models import (
    TraceCompareResponse,
    TraceMetadata,
    TraceStage,
    TraceSummary,
    _redact_secrets,
    _truncate,
)

logger = logging.getLogger("phase8.summarizer")

# Phase 6 attribute names used for extraction
_TARS_ATTRS = {
    "mission_id": "tars.mission.id",
    "incident_id": "tars.incident.id",
    "incident_type": "tars.incident.type",
    "reasoning_id": "tars.reasoning.id",
    "root_cause": "tars.reasoning.root_cause",
    "confidence": "tars.reasoning.confidence",
    "prompt_version": "tars.reasoning.prompt_version",
    "outcome": "tars.reasoning.outcome",
    "model": "llm.model_name",
}

# Span attributes that must never appear in summaries
_UNSAFE_ATTR_PATTERNS = [
    re.compile(r"(?i)(api[_-]?key|password|secret|token|credential)"),
    re.compile(r"(?i)(redis://|bolt://|postgresql://|mysql://)"),
    re.compile(r"(?i)(authorization|bearer)"),
]


def _is_safe_attr(key: str, value: Any) -> bool:
    """Return True if the attribute key/value pair is safe to include."""
    key_lower = key.lower()
    for pattern in _UNSAFE_ATTR_PATTERNS:
        if pattern.search(key_lower):
            return False
        if isinstance(value, str) and pattern.search(value):
            return False
    return True


def _extract_safe_error(span_data: dict[str, Any]) -> Optional[str]:
    """Extract a safe error message from span status or events."""
    # Check status description
    status = span_data.get("status", {})
    if isinstance(status, dict):
        desc = status.get("description", "") or status.get("message", "")
        if desc:
            return _redact_secrets(_truncate(str(desc), 500))

    # Check events for exceptions
    events = span_data.get("events", [])
    if isinstance(events, list):
        for event in events:
            if isinstance(event, dict):
                name = event.get("name", "")
                if name == "exception":
                    attrs = event.get("attributes", {})
                    msg = attrs.get("exception.message", "")
                    if msg:
                        # Never include full stack traces
                        return _redact_secrets(_truncate(str(msg), 500))
    return None


class TraceSummarizer:
    """
    Converts raw Phoenix trace data into safe, bounded summaries.

    Respects the configured content mode to control what information
    is included in summaries.
    """

    def __init__(
        self,
        settings: Optional[PhoenixMCPSettings] = None,
    ) -> None:
        self._settings = settings or mcp_settings

    @property
    def content_mode(self) -> MCPContentMode:
        """Return the current content mode."""
        return self._settings.CONTENT_MODE

    def summarize_trace_metadata(
        self,
        raw_trace: dict[str, Any],
    ) -> TraceMetadata:
        """
        Extract safe metadata from a raw Phoenix trace object.

        Args:
            raw_trace: Raw trace data from Phoenix API.

        Returns:
            TraceMetadata with safe identifiers and attributes.
        """
        # Extract trace ID
        trace_id = str(raw_trace.get("trace_id", raw_trace.get("context", {}).get("trace_id", "")))

        # Extract attributes from root span or trace-level attributes
        attrs = raw_trace.get("attributes", {})
        if not attrs and "spans" in raw_trace:
            spans = raw_trace.get("spans", [])
            if spans and isinstance(spans, list):
                attrs = spans[0].get("attributes", {})

        return TraceMetadata(
            trace_id=trace_id,
            reasoning_id=self._safe_str(attrs.get(_TARS_ATTRS["reasoning_id"])),
            mission_id=self._safe_str(attrs.get(_TARS_ATTRS["mission_id"])),
            incident_id=self._safe_str(attrs.get(_TARS_ATTRS["incident_id"])),
            incident_type=self._safe_str(attrs.get(_TARS_ATTRS["incident_type"])),
            root_cause=self._safe_str(attrs.get(_TARS_ATTRS["root_cause"])),
            confidence=self._safe_float(attrs.get(_TARS_ATTRS["confidence"])),
            prompt_version=self._safe_str(attrs.get(_TARS_ATTRS["prompt_version"])),
            model=self._safe_str(attrs.get(_TARS_ATTRS["model"])),
            outcome=self._safe_str(attrs.get(_TARS_ATTRS["outcome"])),
            duration_ms=self._safe_int(raw_trace.get("duration_ms")),
            created_at=self._safe_str(
                raw_trace.get("created_at")
                or raw_trace.get("start_time")
            ),
        )

    def summarize_trace(
        self,
        raw_trace: dict[str, Any],
    ) -> TraceSummary:
        """
        Convert a raw Phoenix trace into a safe TraceSummary.

        Args:
            raw_trace: Raw trace data from Phoenix API including spans.

        Returns:
            TraceSummary with stage breakdown and optional summary text.
        """
        trace_id = str(raw_trace.get("trace_id", raw_trace.get("context", {}).get("trace_id", "")))

        # Extract spans
        spans = raw_trace.get("spans", [])
        if not isinstance(spans, list):
            spans = []

        # Extract root span info
        root_span_name = None
        attrs = raw_trace.get("attributes", {})

        # Build stages from spans
        stages: list[TraceStage] = []
        for span in spans:
            if not isinstance(span, dict):
                continue

            span_name = span.get("name", "unknown")
            span_attrs = span.get("attributes", {})

            # Identify root span
            if root_span_name is None:
                root_span_name = span_name
                if not attrs:
                    attrs = span_attrs

            # Determine status
            status_data = span.get("status", {})
            if isinstance(status_data, dict):
                status_code = status_data.get("status_code", "UNSET")
                if isinstance(status_code, str):
                    status = status_code.lower()
                else:
                    status = "ok" if status_code == 1 else "error" if status_code == 2 else "unset"
            elif isinstance(status_data, str):
                status = status_data.lower()
            else:
                status = "unset"

            # Normalize status
            if status in ("ok", "1"):
                status = "ok"
            elif status in ("error", "2"):
                status = "error"
            else:
                status = "unset"

            # Extract duration
            duration_ms = self._safe_int(span.get("duration_ms"))
            if duration_ms is None:
                start = span.get("start_time")
                end = span.get("end_time")
                if start is not None and end is not None:
                    try:
                        duration_ms = int((float(end) - float(start)) * 1000)
                    except (ValueError, TypeError):
                        pass

            # Extract safe error
            safe_error = None
            if status == "error":
                safe_error = _extract_safe_error(span)

            stages.append(TraceStage(
                name=span_name,
                status=status,
                duration_ms=duration_ms,
                safe_error=safe_error,
            ))

        # Build summary text if content mode allows
        summary_text = None
        if self._settings.include_summaries and stages:
            summary_text = self._generate_summary(stages, attrs)

        # Determine content mode label
        content_label = self._settings.CONTENT_MODE.value

        # Check truncation
        truncated = False
        if summary_text and len(summary_text) > self._settings.MAX_SUMMARY_CHARS:
            summary_text = _truncate(summary_text, self._settings.MAX_SUMMARY_CHARS)
            truncated = True

        return TraceSummary(
            trace_id=trace_id,
            reasoning_id=self._safe_str(attrs.get(_TARS_ATTRS["reasoning_id"])),
            root_span=root_span_name,
            stages=stages,
            prompt_version=self._safe_str(attrs.get(_TARS_ATTRS["prompt_version"])),
            model=self._safe_str(attrs.get(_TARS_ATTRS["model"])),
            captured_content=content_label,
            summary=summary_text,
            truncated=truncated,
        )

    def compare_traces(
        self,
        summaries: list[TraceSummary],
    ) -> TraceCompareResponse:
        """
        Produce a descriptive comparison of multiple trace summaries.

        This is descriptive only. It must not return accuracy scores,
        success rates, or validated lessons.

        Args:
            summaries: List of TraceSummary objects to compare.

        Returns:
            TraceCompareResponse with observed patterns.
        """
        if not summaries:
            return TraceCompareResponse(
                trace_ids=[],
                not_an_evaluation=True,
            )

        trace_ids = [s.trace_id for s in summaries]

        # Find common attributes
        common_incident_type = self._find_common(
            [self._get_trace_attr(s, "incident_type") for s in summaries]
        )
        common_root_cause = self._find_common(
            [self._get_trace_attr(s, "root_cause") for s in summaries]
        )
        common_prompt_version = self._find_common(
            [s.prompt_version for s in summaries]
        )

        # Find repeated failure stage
        failure_stages: list[str] = []
        for s in summaries:
            for stage in s.stages:
                if stage.status == "error":
                    failure_stages.append(stage.name)

        repeated_failure = None
        if failure_stages:
            # Find most common failure stage
            from collections import Counter
            counts = Counter(failure_stages)
            most_common = counts.most_common(1)[0]
            if most_common[1] > 1 or len(summaries) == 1:
                repeated_failure = most_common[0]

        # Generate observed pattern description
        pattern_parts: list[str] = []
        if common_incident_type:
            pattern_parts.append(
                f"All selected traces involve {common_incident_type} incidents."
            )
        if common_root_cause:
            pattern_parts.append(
                f"Common root cause: {common_root_cause}."
            )
        if repeated_failure:
            pattern_parts.append(
                f"Repeated failure at stage: {repeated_failure}."
            )
        if common_prompt_version:
            pattern_parts.append(
                f"All traces used prompt version {common_prompt_version}."
            )

        if not pattern_parts:
            pattern_parts.append(
                "No strong common pattern detected across selected traces."
            )

        observed_pattern = " ".join(pattern_parts)

        return TraceCompareResponse(
            trace_ids=trace_ids,
            common_incident_type=common_incident_type,
            common_root_cause=common_root_cause,
            common_prompt_version=common_prompt_version,
            repeated_failure_stage=repeated_failure,
            observed_pattern=observed_pattern,
            not_an_evaluation=True,
        )

    # -----------------------------------------------------------------------
    # Internal Helpers
    # -----------------------------------------------------------------------

    def _generate_summary(
        self,
        stages: list[TraceStage],
        attrs: dict[str, Any],
    ) -> str:
        """Generate a bounded text summary from stages and attributes."""
        parts: list[str] = []

        # Outcome summary
        error_stages = [s for s in stages if s.status == "error"]
        ok_stages = [s for s in stages if s.status == "ok"]

        if error_stages:
            failed_names = ", ".join(s.name for s in error_stages[:3])
            parts.append(f"Reasoning failed at: {failed_names}.")
            for es in error_stages[:2]:
                if es.safe_error:
                    parts.append(f"Error in {es.name}: {es.safe_error}.")
        elif ok_stages:
            parts.append(
                f"Reasoning completed successfully through "
                f"{len(ok_stages)} stages."
            )
        else:
            parts.append("Reasoning trace has no completed stages.")

        # Timing summary
        total_ms = sum(
            s.duration_ms for s in stages if s.duration_ms is not None
        )
        if total_ms > 0:
            parts.append(f"Total duration: {total_ms}ms.")

        return " ".join(parts)

    @staticmethod
    def _find_common(values: list[Optional[str]]) -> Optional[str]:
        """Return the value if all non-None values are the same."""
        non_none = [v for v in values if v is not None]
        if not non_none:
            return None
        if len(set(non_none)) == 1:
            return non_none[0]
        return None

    @staticmethod
    def _get_trace_attr(summary: TraceSummary, attr: str) -> Optional[str]:
        """Get a TARS attribute from a trace summary's stages or metadata."""
        # TraceSummary doesn't store all attrs directly; return None
        # for attributes not directly on the model
        return None

    @staticmethod
    def _safe_str(value: Any) -> Optional[str]:
        """Convert to string safely, returning None for missing values."""
        if value is None:
            return None
        s = str(value)
        if not s or s == "None":
            return None
        return _redact_secrets(s)

    @staticmethod
    def _safe_float(value: Any) -> Optional[float]:
        """Convert to float safely, returning None for missing values."""
        if value is None:
            return None
        try:
            f = float(value)
            return max(0.0, min(f, 1.0))
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _safe_int(value: Any) -> Optional[int]:
        """Convert to non-negative int safely."""
        if value is None:
            return None
        try:
            i = int(value)
            return max(0, i)
        except (ValueError, TypeError):
            return None
