"""
Reasoning Models
================
Pydantic models for Phase 5 Gemini reasoning layer.

Defines:
- ReasoningAnalysis: structured output from Gemini reasoning
- ReasoningResult: full persisted result with metadata
- API request/response schemas
- Provider-neutral reasoning interface (Protocol)
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Optional, Protocol, runtime_checkable

from pydantic import BaseModel, Field, field_validator


# =============================================================================
# Shared Validation
# =============================================================================

# Patterns that indicate direct control commands.
# Each uses word boundaries (\b) so "landing" does not match "land".
_CONTROL_PATTERNS = [
    r"\bexecute\b",
    r"\bsend_command\b",
    r"\bsend command\b",
    r"\barm\b",
    r"\bdisarm\b",
    r"\btakeoff\b",
    r"\btake off\b",
    r"\bland\b",
    r"\brtl\b",
    r"\breturn_to_launch\b",
    r"\breturn to launch\b",
    r"\bset_mode\b",
    r"\bset mode\b",
    r"\bkill\b",
    r"\bactuator\b",
    r"\bmavlink\b",
    r"\bmavsdk\b",
    r"\bdescend immediately\b",
    r"\bfly to\b",
]


def _validate_advisory_recommendation(v: str) -> str:
    """Reject recommendations that look like flight-control commands.

    Uses word-boundary matching to avoid false positives on
    compound words like 'landing gear' while catching standalone
    control verbs like 'land the drone'.
    """
    lower = v.lower()
    for pattern in _CONTROL_PATTERNS:
        match = re.search(pattern, lower)
        if match:
            raise ValueError(
                f"Recommendation must be advisory only; "
                f"matched control pattern '{pattern}'"
            )
    return v


# =============================================================================
# Reasoning Analysis (Gemini structured output)
# =============================================================================

class ReasoningAnalysis(BaseModel):
    """
    Structured reasoning output from the Gemini provider.

    This is the raw analysis before metadata is attached.
    All fields must be validated before persistence.
    """
    root_cause: str = Field(
        ...,
        min_length=1,
        description="Most likely concise cause classification.",
    )
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Model confidence from 0.0 to 1.0.",
    )
    recommendation: str = Field(
        ...,
        min_length=1,
        description="Advisory operational recommendation.",
    )
    rationale: str = Field(
        ...,
        min_length=1,
        description="Short explanation grounded in incident evidence.",
    )
    contributing_factors: list[str] = Field(
        default_factory=list,
        description="Evidence-backed supporting factors.",
    )
    uncertainties: list[str] = Field(
        default_factory=list,
        description="Missing information or plausible alternatives.",
    )

    @field_validator("recommendation")
    @classmethod
    def recommendation_must_be_advisory(cls, v: str) -> str:
        """Reject recommendations that look like flight-control commands."""
        return _validate_advisory_recommendation(v)


# =============================================================================
# Reasoning Result (persisted with metadata)
# =============================================================================

class ReasoningResult(BaseModel):
    """
    Full reasoning result with metadata, persisted to Redis.

    Combines the Gemini analysis with execution metadata.
    """
    reasoning_id: str
    mission_id: str
    incident_id: str
    incident_type: str
    root_cause: str
    confidence: float = Field(ge=0.0, le=1.0)
    recommendation: str
    rationale: str
    contributing_factors: list[str] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    model: str
    prompt_version: str
    created_at: str
    advisory_only: bool = Field(default=True)

    @field_validator("recommendation")
    @classmethod
    def recommendation_must_be_advisory(cls, v: str) -> str:
        """Reject recommendations that look like flight-control commands."""
        return _validate_advisory_recommendation(v)

    @field_validator("advisory_only")
    @classmethod
    def must_be_advisory(cls, v: bool) -> bool:
        """advisory_only must always be True."""
        if not v:
            raise ValueError("advisory_only must always be True")
        return v


# =============================================================================
# API Request/Response Schemas
# =============================================================================

class AnalyzeRequest(BaseModel):
    """POST /api/v1/reasoning/analyze/{mission_id}/{incident_id} request."""
    overwrite: bool = Field(default=True)


class AnalyzeResponse(BaseModel):
    """POST /api/v1/reasoning/analyze/{mission_id}/{incident_id} response."""
    reasoning_id: str
    mission_id: str
    incident_id: str
    incident_type: str
    root_cause: str
    confidence: float
    recommendation: str
    rationale: str
    contributing_factors: list[str] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    model: str
    prompt_version: str
    created_at: str
    advisory_only: bool = True


class ReasoningListResponse(BaseModel):
    """GET /api/v1/reasoning/{mission_id} response."""
    mission_id: str
    analyses: list[ReasoningResult] = Field(default_factory=list)
    total: int = 0


class HealthResponse(BaseModel):
    """GET /health response."""
    status: str = "ok"
    redis: str = "ok"
    phase4: str = "ok"
    gemini: str = "ok"
    phoenix: str = "disabled"


# =============================================================================
# Provider Protocol
# =============================================================================

@runtime_checkable
class ReasoningProvider(Protocol):
    """
    Provider-neutral interface for reasoning execution.

    Production uses the ADK Gemini provider.
    Tests use a deterministic fake provider.
    """

    @property
    def model_name(self) -> str:
        """Return the model identifier used by this provider."""
        ...

    def is_configured(self) -> bool:
        """Return True if the provider has valid credentials."""
        ...

    async def analyze(
        self,
        incident: dict,
    ) -> ReasoningAnalysis:
        """
        Produce a root-cause analysis for a single Phase 4 incident.

        Args:
            incident: Bounded Phase 4 incident dict.

        Returns:
            Structured reasoning analysis.

        Raises:
            RuntimeError: If the provider is not configured.
            ValueError: If the model output is malformed.
        """
        ...
