"""
Phase 9 Evaluation Models
=========================
Pydantic models for the Evaluation Layer.

Defines:
- Enums for classification labels, evidence levels, ground-truth sources.
- EvaluationRequest and batch request models.
- GroundTruthLabel model.
- EvaluationMetric model.
- EvaluationResult model.
- API response schemas.
- Health response schema.

All metric scores are bounded [0.0, 1.0].
All results carry advisory_only=True.
Explanations are bounded in length.
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

class ClassificationLabel(str, Enum):
    """Evaluation classification labels."""
    CORRECT = "correct"
    PARTIALLY_CORRECT = "partially_correct"
    INCORRECT = "incorrect"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    NOT_APPLICABLE = "not_applicable"


class EvidenceLevel(str, Enum):
    """Evidence levels ordered from strongest to weakest."""
    OPERATOR_LABEL = "operator_label"
    MISSION_OUTCOME = "mission_outcome"
    DETERMINISTIC_INCIDENT = "deterministic_incident"
    HISTORICAL_CONSISTENCY = "historical_consistency"
    TRACE_METADATA = "trace_metadata"


class GroundTruthSource(str, Enum):
    """Source of a ground-truth label."""
    OPERATOR_LABEL = "operator_label"
    MISSION_OUTCOME = "mission_outcome"
    SYNTHETIC_TEST_CASE = "synthetic_test_case"
    DETERMINISTIC_RULE = "deterministic_rule"


class MetricName(str, Enum):
    """Known evaluation metric names."""
    ROOT_CAUSE_ACCURACY = "root_cause_accuracy"
    RECOMMENDATION_ACCURACY = "recommendation_accuracy"
    RESPONSE_CONSISTENCY = "response_consistency"
    FALSE_POSITIVE = "false_positive"
    FALSE_NEGATIVE = "false_negative"
    OVERALL_SCORE = "overall_score"


# =============================================================================
# Secret Redaction
# =============================================================================

_SECRET_PATTERNS = [
    re.compile(r"(api[_-]?key|token|secret|password|credential|auth)\s*[:=]\s*\S+", re.IGNORECASE),
    re.compile(r"(Bearer|Basic)\s+\S+", re.IGNORECASE),
    re.compile(r"[A-Za-z0-9+/]{40,}={0,2}", re.IGNORECASE),  # base64-like long strings
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
# Ground Truth Label
# =============================================================================

class GroundTruthLabel(BaseModel):
    """
    Explicit ground-truth label for evaluation.

    Labels must declare their source. LLM judgment without an explicit
    label or outcome is not accepted as ground truth.
    """
    root_cause: Optional[str] = Field(
        default=None,
        description="Accepted root-cause classification.",
    )
    preferred_mitigation: Optional[str] = Field(
        default=None,
        description="Preferred or successful mitigation action.",
    )
    outcome: Optional[str] = Field(
        default=None,
        description="Mission or incident outcome (e.g., recovered, failed).",
    )
    source: GroundTruthSource = Field(
        ...,
        description="Source of this label.",
    )
    labeled_by: Optional[str] = Field(
        default=None,
        description="Actor or system that created this label.",
    )
    labeled_at: Optional[datetime] = Field(
        default=None,
        description="When this label was created.",
    )


class GroundTruthLabelCreate(BaseModel):
    """Request model for creating/updating a ground-truth label."""
    mission_id: str = Field(..., min_length=1)
    incident_id: Optional[str] = Field(default=None)
    root_cause: Optional[str] = Field(default=None)
    preferred_mitigation: Optional[str] = Field(default=None)
    outcome: Optional[str] = Field(default=None)
    source: GroundTruthSource = Field(...)
    labeled_by: Optional[str] = Field(default=None)
    labeled_at: Optional[datetime] = Field(default=None)


class GroundTruthLabelResponse(BaseModel):
    """Response model for a stored ground-truth label."""
    label_id: str
    mission_id: str
    incident_id: Optional[str] = None
    root_cause: Optional[str] = None
    preferred_mitigation: Optional[str] = None
    outcome: Optional[str] = None
    source: GroundTruthSource
    labeled_by: Optional[str] = None
    labeled_at: Optional[datetime] = None
    created_at: datetime


# =============================================================================
# Evaluation Request
# =============================================================================

class GroundTruthPayload(BaseModel):
    """Inline ground-truth payload in an evaluation request."""
    root_cause: Optional[str] = None
    preferred_mitigation: Optional[str] = None
    outcome: Optional[str] = None


class EvaluationRequest(BaseModel):
    """
    Request to evaluate one reasoning result or mission-level target.

    Fields:
    - mission_id: Required mission identifier.
    - incident_id: Optional; null for mission-level false-negative checks.
    - reasoning_id: Optional; null for incident-detection-only evaluation.
    - trace_id: Optional Phoenix trace correlation.
    - ground_truth: Optional inline label payload.
    - evaluate_consistency: Whether to compare against similar cases.
    - overwrite: Whether to replace an existing evaluation.
    """
    mission_id: str = Field(..., min_length=1)
    incident_id: Optional[str] = Field(default=None)
    reasoning_id: Optional[str] = Field(default=None)
    trace_id: Optional[str] = Field(default=None)
    ground_truth: Optional[GroundTruthPayload] = Field(default=None)
    evaluate_consistency: bool = Field(default=True)
    overwrite: bool = Field(default=False)


class BatchEvaluationRequest(BaseModel):
    """Request to evaluate a bounded list of targets."""
    targets: list[EvaluationRequest] = Field(
        ...,
        min_length=1,
        description="List of evaluation targets.",
    )

    @field_validator("targets")
    @classmethod
    def validate_batch_size(cls, v: list[EvaluationRequest]) -> list[EvaluationRequest]:
        """Enforce maximum batch size from config."""
        if len(v) > settings.EVALUATION_BATCH_LIMIT:
            raise ValueError(
                f"Batch size {len(v)} exceeds maximum "
                f"{settings.EVALUATION_BATCH_LIMIT}"
            )
        return v


# =============================================================================
# Evaluation Metric
# =============================================================================

class EvaluationMetric(BaseModel):
    """
    Single evaluation metric with score, label, evidence, and explanation.

    Scores are bounded [0.0, 1.0] or null for insufficient evidence.
    """
    name: MetricName = Field(
        ...,
        description="Metric identifier.",
    )
    score: Optional[float] = Field(
        default=None,
        description="Metric score from 0.0 to 1.0, or null.",
    )
    label: ClassificationLabel = Field(
        ...,
        description="Classification label for this metric.",
    )
    evidence: list[str] = Field(
        default_factory=list,
        description="Evidence levels supporting this score.",
    )
    explanation: str = Field(
        ...,
        min_length=1,
        description="Bounded explanation of the score.",
    )

    @field_validator("score")
    @classmethod
    def validate_score_bounds(cls, v: Optional[float]) -> Optional[float]:
        """Ensure score is within [0.0, 1.0] or null."""
        if v is not None:
            if v < 0.0 or v > 1.0:
                raise ValueError(
                    f"Metric score {v} is out of bounds [0.0, 1.0]"
                )
        return v

    @field_validator("explanation")
    @classmethod
    def truncate_explanation(cls, v: str) -> str:
        """Truncate and redact explanation text."""
        return _truncate_and_redact(v, settings.MAX_EXPLANATION_LENGTH)


# =============================================================================
# Evaluation Result
# =============================================================================

class EvaluationResult(BaseModel):
    """
    Complete evaluation result with metrics, scores, and provenance.

    All results carry advisory_only=True. Results must not contain
    raw prompts, full trace bodies, credentials, or raw telemetry.
    """
    evaluation_id: str = Field(
        ...,
        description="Unique evaluation identifier.",
    )
    mission_id: str = Field(
        ...,
        description="Mission identifier.",
    )
    incident_id: Optional[str] = Field(
        default=None,
        description="Incident identifier (null for mission-level).",
    )
    reasoning_id: Optional[str] = Field(
        default=None,
        description="Reasoning result identifier.",
    )
    trace_id: Optional[str] = Field(
        default=None,
        description="Phoenix trace correlation ID.",
    )
    metrics: list[EvaluationMetric] = Field(
        default_factory=list,
        description="Individual metric evaluations.",
    )
    overall_score: Optional[float] = Field(
        default=None,
        description="Weighted aggregate score [0.0, 1.0].",
    )
    false_positive: bool = Field(
        default=False,
        description="Whether this is a false positive.",
    )
    false_negative: bool = Field(
        default=False,
        description="Whether this is a false negative.",
    )
    evidence_level: Optional[str] = Field(
        default=None,
        description="Strongest evidence level used.",
    )
    evaluator_version: str = Field(
        ...,
        description="Version of the evaluator that produced this result.",
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="When this evaluation was created.",
    )
    advisory_only: bool = Field(
        default=True,
        description="Must always be True.",
    )

    @field_validator("overall_score")
    @classmethod
    def validate_overall_score(cls, v: Optional[float]) -> Optional[float]:
        """Ensure overall score is within [0.0, 1.0] or null."""
        if v is not None:
            if v < 0.0 or v > 1.0:
                raise ValueError(
                    f"Overall score {v} is out of bounds [0.0, 1.0]"
                )
        return v

    @field_validator("advisory_only")
    @classmethod
    def must_be_advisory(cls, v: bool) -> bool:
        """advisory_only must always be True."""
        if not v:
            raise ValueError("advisory_only must always be True")
        return v


# =============================================================================
# API Response Models
# =============================================================================

class EvaluationResponse(BaseModel):
    """POST /api/v1/evaluations/evaluate response."""
    evaluation_id: str
    mission_id: str
    incident_id: Optional[str] = None
    reasoning_id: Optional[str] = None
    overall_score: Optional[float] = None
    false_positive: bool = False
    false_negative: bool = False
    metrics: list[EvaluationMetric] = Field(default_factory=list)
    evidence_level: Optional[str] = None
    evaluator_version: str = ""
    created_at: Optional[datetime] = None
    advisory_only: bool = True


class BatchItemResult(BaseModel):
    """Result for one item in a batch evaluation."""
    index: int
    success: bool
    evaluation: Optional[EvaluationResponse] = None
    error: Optional[str] = None


class BatchEvaluationResponse(BaseModel):
    """POST /api/v1/evaluations/batch response."""
    total: int
    succeeded: int
    failed: int
    results: list[BatchItemResult] = Field(default_factory=list)


class EvaluationListResponse(BaseModel):
    """GET /api/v1/evaluations/mission/{mission_id} response."""
    mission_id: str
    evaluations: list[EvaluationResponse] = Field(default_factory=list)
    total: int = 0


class ReasoningEvaluationListResponse(BaseModel):
    """GET /api/v1/evaluations/reasoning/{reasoning_id} response."""
    reasoning_id: str
    evaluations: list[EvaluationResponse] = Field(default_factory=list)
    total: int = 0


class HealthResponse(BaseModel):
    """GET /health response."""
    status: str = "ok"
    postgres: str = "unavailable"
    phase4: str = "unknown"
    phase5: str = "unknown"
    phase7: str = "disabled"
    phoenix: str = "disabled"
