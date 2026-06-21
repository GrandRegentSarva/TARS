"""
Phase 10 Learning Models
=========================
Pydantic models for the Learning Engine.

Defines:
- Enums for candidate types, statuses, evidence levels, and run statuses.
- LearningRunRequest and response models.
- LearningEvidence model.
- CandidateKnowledge model.
- API response schemas.
- Health response schema.

All confidence scores are bounded [0.0, 1.0].
All candidates carry advisory_only=True.
Statements are bounded in length and secret-redacted.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator

from .config import settings


# =============================================================================
# Enums
# =============================================================================

class CandidateType(str, Enum):
    """Types of candidate knowledge."""
    MITIGATION_EFFECTIVENESS = "mitigation_effectiveness"
    ROOT_CAUSE_PATTERN = "root_cause_pattern"
    REASONING_QUALITY_PATTERN = "reasoning_quality_pattern"
    FALSE_POSITIVE_PATTERN = "false_positive_pattern"
    FALSE_NEGATIVE_PATTERN = "false_negative_pattern"
    RISK_CONTEXT_PATTERN = "risk_context_pattern"


class CandidateStatus(str, Enum):
    """Lifecycle statuses for candidate knowledge."""
    PROPOSED = "proposed"
    SUPERSEDED = "superseded"
    RETIRED = "retired"
    REJECTED = "rejected"


class LearningRunStatus(str, Enum):
    """Statuses for a learning run."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETE = "complete"
    FAILED = "failed"


class EvidenceLevel(str, Enum):
    """Evidence strength levels ordered from strongest to weakest."""
    OPERATOR_LABEL = "operator_label"
    MISSION_OUTCOME = "mission_outcome"
    DETERMINISTIC_INCIDENT = "deterministic_incident"
    EVALUATION_METRIC = "evaluation_metric"
    OPERATIONAL_MEMORY = "operational_memory"
    TRACE_METADATA = "trace_metadata"


class RunCandidateAction(str, Enum):
    """Actions taken on a candidate during a learning run."""
    PROPOSED = "proposed"
    UPDATED = "updated"
    SUPPRESSED = "suppressed"
    UNCHANGED = "unchanged"


# =============================================================================
# Secret Redaction
# =============================================================================

_SECRET_PATTERNS = [
    re.compile(
        r"(api[_-]?key|token|secret|password|credential|auth)\s*[:=]\s*\S+",
        re.IGNORECASE,
    ),
    re.compile(r"(Bearer|Basic)\s+\S+", re.IGNORECASE),
    re.compile(r"[A-Za-z0-9+/]{40,}={0,2}", re.IGNORECASE),
]


def _redact_secrets(text: str) -> str:
    """Redact potential secrets from text."""
    result = text
    for pattern in _SECRET_PATTERNS:
        result = pattern.sub("[REDACTED]", result)
    return result


def _truncate_and_redact(text: str, max_length: int) -> str:
    """Truncate text to max_length and redact secrets."""
    redacted = _redact_secrets(text)
    if len(redacted) > max_length:
        return redacted[:max_length]
    return redacted


# =============================================================================
# Learning Run Request
# =============================================================================

class LearningRunRequest(BaseModel):
    """
    Request to start a bounded learning run.

    All filters are optional. Date ranges must be bounded.
    dry_run=true returns candidates without persistence.
    """
    mission_ids: list[str] = Field(
        default_factory=list,
        description="Optional mission ID filter.",
    )
    incident_family: Optional[str] = Field(
        default=None,
        description="Optional incident family filter.",
    )
    root_cause: Optional[str] = Field(
        default=None,
        description="Optional root cause filter.",
    )
    candidate_types: list[CandidateType] = Field(
        default_factory=lambda: list(CandidateType),
        description="Candidate types to mine. Defaults to all.",
    )
    since: Optional[datetime] = Field(
        default=None,
        description="Start of evaluation date range.",
    )
    until: Optional[datetime] = Field(
        default=None,
        description="End of evaluation date range.",
    )
    min_evaluated_cases: int = Field(
        default=5,
        ge=1,
        description="Minimum evaluated cases per candidate.",
    )
    dry_run: bool = Field(
        default=False,
        description="If true, return candidates without persisting.",
    )

    @field_validator("mission_ids")
    @classmethod
    def validate_mission_ids_bounded(cls, v: list[str]) -> list[str]:
        """Enforce bounded mission ID list."""
        if len(v) > settings.LEARNING_BATCH_LIMIT:
            raise ValueError(
                f"mission_ids count {len(v)} exceeds batch limit "
                f"{settings.LEARNING_BATCH_LIMIT}"
            )
        return v


# =============================================================================
# Learning Evidence
# =============================================================================

class LearningEvidence(BaseModel):
    """
    Single evidence item linking an evaluation to a candidate.

    Evidence carries identifiers, not unbounded source payloads.
    Trace IDs are allowed; trace bodies are not.
    """
    evidence_id: str = Field(
        ...,
        description="Unique evidence identifier.",
    )
    mission_id: str = Field(
        ...,
        description="Mission identifier.",
    )
    incident_id: Optional[str] = Field(
        default=None,
        description="Incident identifier.",
    )
    reasoning_id: Optional[str] = Field(
        default=None,
        description="Reasoning result identifier.",
    )
    evaluation_id: Optional[str] = Field(
        default=None,
        description="Phase 9 evaluation identifier.",
    )
    trace_id: Optional[str] = Field(
        default=None,
        description="Phoenix trace identifier (ID only).",
    )
    root_cause: Optional[str] = Field(
        default=None,
        description="Root cause classification.",
    )
    mitigation: Optional[str] = Field(
        default=None,
        description="Mitigation action.",
    )
    outcome: Optional[str] = Field(
        default=None,
        description="Mission or incident outcome.",
    )
    overall_score: Optional[float] = Field(
        default=None,
        description="Phase 9 overall evaluation score.",
    )
    metric_labels: dict[str, str] = Field(
        default_factory=dict,
        description="Phase 9 metric classification labels.",
    )
    evidence_levels: list[str] = Field(
        default_factory=list,
        description="Evidence strength levels present.",
    )

    @field_validator("overall_score")
    @classmethod
    def validate_score_bounds(cls, v: Optional[float]) -> Optional[float]:
        """Ensure score is within [0.0, 1.0] or null."""
        if v is not None and (v < 0.0 or v > 1.0):
            raise ValueError(
                f"overall_score {v} is out of bounds [0.0, 1.0]"
            )
        return v


# =============================================================================
# Candidate Knowledge
# =============================================================================

class CandidateKnowledge(BaseModel):
    """
    A candidate knowledge record with evidence, confidence, and provenance.

    Candidate knowledge is not truth. It is a structured hypothesis
    backed by auditable evidence. advisory_only must always be True.
    """
    candidate_id: str = Field(
        ...,
        description="Unique candidate identifier.",
    )
    candidate_type: CandidateType = Field(
        ...,
        description="Type of candidate knowledge.",
    )
    status: CandidateStatus = Field(
        default=CandidateStatus.PROPOSED,
        description="Lifecycle status.",
    )
    statement: str = Field(
        ...,
        min_length=1,
        description="Deterministic template-generated statement.",
    )
    incident_family: Optional[str] = Field(
        default=None,
        description="Incident family this candidate applies to.",
    )
    root_cause: Optional[str] = Field(
        default=None,
        description="Root cause this candidate relates to.",
    )
    mitigation: Optional[str] = Field(
        default=None,
        description="Mitigation action this candidate relates to.",
    )
    outcome_family: Optional[str] = Field(
        default=None,
        description="Outcome family (e.g., recovered_or_stabilized).",
    )
    support_count: int = Field(
        default=0,
        ge=0,
        description="Number of supporting evidence items.",
    )
    contradiction_count: int = Field(
        default=0,
        ge=0,
        description="Number of contradicting evidence items.",
    )
    distinct_mission_count: int = Field(
        default=0,
        ge=0,
        description="Number of distinct missions in evidence.",
    )
    success_rate: float = Field(
        default=0.0,
        description="Rate of successful outcomes [0.0, 1.0].",
    )
    mean_overall_score: Optional[float] = Field(
        default=None,
        description="Mean Phase 9 overall score across evidence.",
    )
    confidence: float = Field(
        default=0.0,
        description="Candidate confidence score [0.0, 1.0].",
    )
    evidence_ids: list[str] = Field(
        default_factory=list,
        description="Evidence item identifiers.",
    )
    source_evaluation_ids: list[str] = Field(
        default_factory=list,
        description="Source Phase 9 evaluation identifiers.",
    )
    source_trace_ids: list[str] = Field(
        default_factory=list,
        description="Source Phoenix trace identifiers.",
    )
    learning_version: str = Field(
        default="",
        description="Learning engine version that created this candidate.",
    )
    dedupe_key: str = Field(
        default="",
        description="Deterministic deduplication key.",
    )
    supersedes_candidate_id: Optional[str] = Field(
        default=None,
        description="ID of the candidate this one supersedes.",
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="When this candidate was created.",
    )
    updated_at: Optional[datetime] = Field(
        default=None,
        description="When this candidate was last updated.",
    )
    advisory_only: bool = Field(
        default=True,
        description="Must always be True.",
    )

    @field_validator("confidence")
    @classmethod
    def validate_confidence_bounds(cls, v: float) -> float:
        """Ensure confidence is within [0.0, 1.0]."""
        if v < 0.0 or v > 1.0:
            raise ValueError(
                f"confidence {v} is out of bounds [0.0, 1.0]"
            )
        return v

    @field_validator("success_rate")
    @classmethod
    def validate_success_rate_bounds(cls, v: float) -> float:
        """Ensure success_rate is within [0.0, 1.0]."""
        if v < 0.0 or v > 1.0:
            raise ValueError(
                f"success_rate {v} is out of bounds [0.0, 1.0]"
            )
        return v

    @field_validator("mean_overall_score")
    @classmethod
    def validate_mean_score_bounds(cls, v: Optional[float]) -> Optional[float]:
        """Ensure mean_overall_score is within [0.0, 1.0] or null."""
        if v is not None and (v < 0.0 or v > 1.0):
            raise ValueError(
                f"mean_overall_score {v} is out of bounds [0.0, 1.0]"
            )
        return v

    @field_validator("advisory_only")
    @classmethod
    def must_be_advisory(cls, v: bool) -> bool:
        """advisory_only must always be True."""
        if not v:
            raise ValueError("advisory_only must always be True")
        return v

    @field_validator("statement")
    @classmethod
    def truncate_statement(cls, v: str) -> str:
        """Truncate and redact statement text."""
        return _truncate_and_redact(v, settings.MAX_STATEMENT_LENGTH)


# =============================================================================
# Learning Run Response
# =============================================================================

class LearningRunResponse(BaseModel):
    """Response from a learning run."""
    run_id: str = Field(
        ...,
        description="Unique learning run identifier.",
    )
    status: LearningRunStatus = Field(
        ...,
        description="Run status.",
    )
    started_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="When the run started.",
    )
    completed_at: Optional[datetime] = Field(
        default=None,
        description="When the run completed.",
    )
    filters: dict = Field(
        default_factory=dict,
        description="Filters applied to this run.",
    )
    evaluated_cases_read: int = Field(
        default=0,
        ge=0,
        description="Number of evaluation records read.",
    )
    evidence_items_used: int = Field(
        default=0,
        ge=0,
        description="Number of evidence items used.",
    )
    candidates_proposed: int = Field(
        default=0,
        ge=0,
        description="Number of new candidates proposed.",
    )
    candidates_updated: int = Field(
        default=0,
        ge=0,
        description="Number of existing candidates updated.",
    )
    candidates_suppressed: int = Field(
        default=0,
        ge=0,
        description="Number of candidates suppressed (below thresholds).",
    )
    candidate_ids: list[str] = Field(
        default_factory=list,
        description="IDs of proposed or updated candidates.",
    )
    warnings: list[str] = Field(
        default_factory=list,
        description="Non-fatal warnings from the run.",
    )
    error_code: Optional[str] = Field(
        default=None,
        description="Error code if run failed.",
    )
    error_message: Optional[str] = Field(
        default=None,
        description="Error message if run failed.",
    )
    learning_version: str = Field(
        default="",
        description="Learning engine version used.",
    )
    dry_run: bool = Field(
        default=False,
        description="Whether this was a dry run.",
    )


# =============================================================================
# API Response Models
# =============================================================================

class CandidateResponse(BaseModel):
    """Single candidate in API responses."""
    candidate_id: str
    candidate_type: CandidateType
    status: CandidateStatus
    statement: str
    incident_family: Optional[str] = None
    root_cause: Optional[str] = None
    mitigation: Optional[str] = None
    outcome_family: Optional[str] = None
    support_count: int = 0
    contradiction_count: int = 0
    distinct_mission_count: int = 0
    success_rate: float = 0.0
    mean_overall_score: Optional[float] = None
    confidence: float = 0.0
    evidence_ids: list[str] = Field(default_factory=list)
    source_evaluation_ids: list[str] = Field(default_factory=list)
    source_trace_ids: list[str] = Field(default_factory=list)
    learning_version: str = ""
    dedupe_key: str = ""
    supersedes_candidate_id: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    advisory_only: bool = True


class CandidateListResponse(BaseModel):
    """GET /api/v1/learning/candidates response."""
    candidates: list[CandidateResponse] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 50


class EvidenceResponse(BaseModel):
    """Single evidence item in API responses."""
    evidence_id: str
    candidate_id: str
    mission_id: str
    incident_id: Optional[str] = None
    reasoning_id: Optional[str] = None
    evaluation_id: Optional[str] = None
    trace_id: Optional[str] = None
    root_cause: Optional[str] = None
    mitigation: Optional[str] = None
    outcome: Optional[str] = None
    overall_score: Optional[float] = None
    metric_labels: dict[str, str] = Field(default_factory=dict)
    evidence_levels: list[str] = Field(default_factory=list)
    created_at: Optional[datetime] = None


class EvidenceListResponse(BaseModel):
    """GET /api/v1/learning/candidates/{id}/evidence response."""
    candidate_id: str
    evidence: list[EvidenceResponse] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 50


class RetireRequest(BaseModel):
    """POST /api/v1/learning/candidates/{id}/retire request."""
    reason: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Reason for retiring this candidate.",
    )


class HealthResponse(BaseModel):
    """GET /health response."""
    status: str = "ok"
    postgres: str = "unavailable"
    phase9: str = "unknown"
    phase7: str = "disabled"
    phoenix: str = "disabled"
    learning_version: str = ""
