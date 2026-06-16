"""
Phase 8 Models
==============
Pydantic models for Phoenix MCP self-introspection tool contracts.

Defines:
- Tool request models with bounded inputs.
- Safe trace summary models with content limits.
- Introspection metadata for reasoning integration.
- Comparison output with descriptive-only markers.

All models enforce:
- Positive limits capped to configured maximums.
- Required trace IDs and safe status fields.
- ``not_an_evaluation=True`` on comparison outputs.
- Truncation markers on overlong summaries.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator


# =============================================================================
# Configuration Defaults (overridden at runtime by config.py)
# =============================================================================

_DEFAULT_LIMIT = 5
_MAX_LIMIT = 20
_MAX_TRACE_IDS = 10
_MAX_SUMMARY_CHARS = 2000

# Patterns that indicate secrets or unsafe content
# Each pattern captures the keyword AND any following value (e.g., key=value)
_SECRET_PATTERNS = [
    re.compile(r"(?i)(api[_-]?key|password|secret|token|credential|auth)\s*[=:]\s*\S+"),
    re.compile(r"(?i)(api[_-]?key|password|secret|token|credential|auth)"),
    re.compile(r"(?i)(redis://\S+|bolt://\S+|postgresql://\S+|mysql://\S+)"),
    re.compile(r"(?i)(bearer\s+\S+)"),
]


def _redact_secrets(text: str) -> str:
    """Replace secret-like patterns with [REDACTED]."""
    result = text
    for pattern in _SECRET_PATTERNS:
        result = pattern.sub("[REDACTED]", result)
    return result


def _truncate(text: str, max_chars: int = _MAX_SUMMARY_CHARS) -> str:
    """Truncate text to max_chars, appending '...[truncated]' if needed."""
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 14] + "...[truncated]"


# =============================================================================
# Tool Request Models
# =============================================================================

class TraceSearchRequest(BaseModel):
    """
    Input for ``search_reasoning_traces`` tool.

    All fields are optional filters. At least one filter should be
    provided for meaningful results.
    """

    mission_id: Optional[str] = Field(
        default=None,
        description="Filter by mission identifier.",
    )
    incident_id: Optional[str] = Field(
        default=None,
        description="Filter by incident identifier.",
    )
    incident_type: Optional[str] = Field(
        default=None,
        description="Filter by incident type classification.",
    )
    root_cause: Optional[str] = Field(
        default=None,
        description="Filter by root cause classification.",
    )
    prompt_version: Optional[str] = Field(
        default=None,
        description="Filter by prompt version.",
    )
    model: Optional[str] = Field(
        default=None,
        description="Filter by model identifier.",
    )
    outcome: Optional[str] = Field(
        default=None,
        description="Filter by outcome (success, failed, cached).",
    )
    from_time: Optional[str] = Field(
        default=None,
        description="Start of time range (ISO 8601).",
    )
    to_time: Optional[str] = Field(
        default=None,
        description="End of time range (ISO 8601).",
    )
    limit: int = Field(
        default=_DEFAULT_LIMIT,
        ge=1,
        description="Maximum number of traces to return.",
    )

    @field_validator("limit")
    @classmethod
    def cap_limit(cls, v: int) -> int:
        """Cap limit to configured maximum."""
        return min(v, _MAX_LIMIT)

    @field_validator("outcome")
    @classmethod
    def validate_outcome(cls, v: Optional[str]) -> Optional[str]:
        """Validate outcome is a known value."""
        if v is not None and v not in ("success", "failed", "cached"):
            raise ValueError(
                f"outcome must be 'success', 'failed', or 'cached'; got '{v}'"
            )
        return v


class TraceSummaryRequest(BaseModel):
    """
    Input for ``get_reasoning_trace_summary`` tool.
    """

    trace_id: str = Field(
        ...,
        min_length=1,
        description="Phoenix trace identifier.",
    )


class TraceCompareRequest(BaseModel):
    """
    Input for ``compare_reasoning_traces`` tool.

    Accepts a bounded list of trace IDs for descriptive comparison.
    """

    trace_ids: list[str] = Field(
        ...,
        min_length=1,
        description="List of trace IDs to compare.",
    )

    @field_validator("trace_ids")
    @classmethod
    def cap_trace_ids(cls, v: list[str]) -> list[str]:
        """Cap trace ID list to configured maximum."""
        if len(v) > _MAX_TRACE_IDS:
            return v[:_MAX_TRACE_IDS]
        return v

    @field_validator("trace_ids")
    @classmethod
    def no_empty_ids(cls, v: list[str]) -> list[str]:
        """Reject empty trace IDs."""
        filtered = [tid for tid in v if tid.strip()]
        if not filtered:
            raise ValueError("trace_ids must contain at least one non-empty ID")
        return filtered


# =============================================================================
# Safe Trace Summary Models
# =============================================================================

class TraceStage(BaseModel):
    """
    A single stage (span) within a reasoning trace.

    Contains only safe metadata: name, status, timing, and
    optionally a redacted error message.
    """

    name: str = Field(
        ...,
        description="Span name (e.g., 'phase4.get_incident', 'gemini.generate').",
    )
    status: str = Field(
        ...,
        description="Span status: 'ok', 'error', or 'unset'.",
    )
    duration_ms: Optional[int] = Field(
        default=None,
        ge=0,
        description="Span duration in milliseconds.",
    )
    safe_error: Optional[str] = Field(
        default=None,
        description="Redacted error message (no secrets).",
    )

    @field_validator("safe_error")
    @classmethod
    def redact_error(cls, v: Optional[str]) -> Optional[str]:
        """Redact any secret-like content from error messages."""
        if v is not None:
            return _redact_secrets(_truncate(v, 500))
        return v


class TraceMetadata(BaseModel):
    """
    Bounded metadata for a single reasoning trace.

    Used in search results. Contains only safe identifiers and
    operational attributes.
    """

    trace_id: str
    reasoning_id: Optional[str] = None
    mission_id: Optional[str] = None
    incident_id: Optional[str] = None
    incident_type: Optional[str] = None
    root_cause: Optional[str] = None
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    prompt_version: Optional[str] = None
    model: Optional[str] = None
    outcome: Optional[str] = None
    duration_ms: Optional[int] = Field(default=None, ge=0)
    created_at: Optional[str] = None


class TraceSummary(BaseModel):
    """
    Safe summary for a single reasoning trace.

    Includes stage breakdown and an optional generated summary.
    Never includes raw prompt/response bodies in default mode.
    """

    trace_id: str
    reasoning_id: Optional[str] = None
    root_span: Optional[str] = None
    stages: list[TraceStage] = Field(default_factory=list)
    prompt_version: Optional[str] = None
    model: Optional[str] = None
    captured_content: str = Field(
        default="metadata",
        description="Content mode used: 'metadata', 'summary', or 'full_dev'.",
    )
    summary: Optional[str] = None
    truncated: bool = False

    @field_validator("summary")
    @classmethod
    def truncate_summary(cls, v: Optional[str]) -> Optional[str]:
        """Truncate overlong summaries."""
        if v is not None and len(v) > _MAX_SUMMARY_CHARS:
            return _truncate(v, _MAX_SUMMARY_CHARS)
        return v


# =============================================================================
# Tool Response Models
# =============================================================================

class TraceSearchResponse(BaseModel):
    """
    Response from ``search_reasoning_traces`` tool.
    """

    traces: list[TraceMetadata] = Field(default_factory=list)
    total: int = 0
    truncated: bool = False


class TraceSummaryResponse(BaseModel):
    """
    Response from ``get_reasoning_trace_summary`` tool.

    Wraps a single TraceSummary.
    """

    trace_id: str
    reasoning_id: Optional[str] = None
    root_span: Optional[str] = None
    stages: list[TraceStage] = Field(default_factory=list)
    prompt_version: Optional[str] = None
    model: Optional[str] = None
    captured_content: str = "metadata"
    summary: Optional[str] = None
    truncated: bool = False

    @field_validator("summary")
    @classmethod
    def truncate_summary(cls, v: Optional[str]) -> Optional[str]:
        """Truncate overlong summaries."""
        if v is not None and len(v) > _MAX_SUMMARY_CHARS:
            return _truncate(v, _MAX_SUMMARY_CHARS)
        return v


class TraceCompareResponse(BaseModel):
    """
    Response from ``compare_reasoning_traces`` tool.

    Descriptive comparison only. ``not_an_evaluation`` is always True.
    """

    trace_ids: list[str] = Field(default_factory=list)
    common_incident_type: Optional[str] = None
    common_root_cause: Optional[str] = None
    common_prompt_version: Optional[str] = None
    repeated_failure_stage: Optional[str] = None
    observed_pattern: Optional[str] = None
    not_an_evaluation: bool = Field(
        default=True,
        description="Always True. This comparison is descriptive, not evaluative.",
    )

    @field_validator("not_an_evaluation")
    @classmethod
    def must_not_be_evaluation(cls, v: bool) -> bool:
        """Enforce that comparison output is never marked as evaluation."""
        if not v:
            raise ValueError(
                "not_an_evaluation must always be True; "
                "Phase 8 comparisons are descriptive only"
            )
        return v

    @field_validator("observed_pattern")
    @classmethod
    def truncate_pattern(cls, v: Optional[str]) -> Optional[str]:
        """Truncate overlong pattern descriptions."""
        if v is not None and len(v) > _MAX_SUMMARY_CHARS:
            return _truncate(v, _MAX_SUMMARY_CHARS)
        return v


# =============================================================================
# Introspection Metadata (for Phase 5 integration)
# =============================================================================

class IntrospectionContext(BaseModel):
    """
    Bounded introspection context added to Phase 5 reasoning prompts.

    Contains only safe summary information. Never includes raw trace
    bodies, credentials, or evaluation scores.
    """

    source: str = Field(
        default="phoenix_mcp",
        description="Source of introspection data.",
    )
    traces_consulted: list[str] = Field(
        default_factory=list,
        description="Trace IDs that were consulted.",
    )
    summary: list[str] = Field(
        default_factory=list,
        description="Bounded summary statements from trace analysis.",
    )
    limitations: list[str] = Field(
        default_factory=lambda: [
            "Trace history is descriptive and not an evaluation.",
            "No accuracy labels are available in Phase 8.",
        ],
        description="Explicit limitations of introspection data.",
    )

    @field_validator("summary")
    @classmethod
    def truncate_summaries(cls, v: list[str]) -> list[str]:
        """Truncate individual summary items."""
        return [_truncate(s, 500) for s in v[:20]]


class IntrospectionResult(BaseModel):
    """
    Safe introspection metadata persisted on reasoning results.

    Contains only provenance information, not raw trace content.
    """

    introspection_used: bool = False
    introspection_trace_ids: list[str] = Field(default_factory=list)
    introspection_summary: Optional[str] = None

    @field_validator("introspection_summary")
    @classmethod
    def truncate_result_summary(cls, v: Optional[str]) -> Optional[str]:
        """Truncate overlong result summaries."""
        if v is not None and len(v) > _MAX_SUMMARY_CHARS:
            return _truncate(v, _MAX_SUMMARY_CHARS)
        return v
