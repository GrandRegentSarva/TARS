"""
Phase 7 Models
==============
Pydantic models for the Neo4j Operational Memory service.

Defines:
- Graph node property contracts
- Sync request/response schemas
- Observation request/response schemas (mitigations, outcomes)
- Query response schemas (incident memory, similar history)
- Health response schema
- Controlled enums for outcome status and sync status
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator


# =============================================================================
# Enums
# =============================================================================

class OutcomeStatus(str, Enum):
    """Controlled outcome statuses for incident or mission outcomes."""
    RECOVERED = "recovered"
    STABILIZED = "stabilized"
    DEGRADED = "degraded"
    FAILED = "failed"
    UNKNOWN = "unknown"


class SyncStatus(str, Enum):
    """Sync job status for mission memory projection."""
    PROCESSING = "processing"
    COMPLETE = "complete"
    FAILED = "failed"


class OutcomeScope(str, Enum):
    """Scope of an outcome observation."""
    MISSION = "mission"
    INCIDENT = "incident"


class MitigationSource(str, Enum):
    """Source of a mitigation record."""
    PHASE5_RECOMMENDATION = "phase5_recommendation"
    EXPLICIT_OBSERVATION = "explicit_observation"


class OutcomeSource(str, Enum):
    """Source of an outcome record."""
    PHASE2_MISSION_RESULT = "phase2_mission_result"
    EXPLICIT_OBSERVATION = "explicit_observation"


# =============================================================================
# Sync Request/Response
# =============================================================================

class SyncRequest(BaseModel):
    """POST /api/v1/memory/sync/{mission_id} request body."""
    include_reasoning: bool = Field(
        default=True,
        description="Whether to fetch and project Phase 5 reasoning analyses.",
    )
    require_reasoning: bool = Field(
        default=False,
        description=(
            "When true, fail the sync if Phase 5 is unavailable. "
            "When false, store mission and incidents while skipping reasoning."
        ),
    )


class SyncCounts(BaseModel):
    """Projection counts from a sync operation."""
    missions: int = 0
    incidents: int = 0
    root_causes: int = 0
    mitigations: int = 0
    outcomes: int = 0
    relationships: int = 0
    analyses_skipped: int = 0


class SyncResponse(BaseModel):
    """POST /api/v1/memory/sync/{mission_id} response body."""
    mission_id: str
    status: SyncStatus
    counts: SyncCounts = Field(default_factory=SyncCounts)
    started_at: datetime
    completed_at: Optional[datetime] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None


class SyncStatusResponse(BaseModel):
    """GET /api/v1/memory/sync/{mission_id} response body."""
    mission_id: str
    status: SyncStatus
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    counts: SyncCounts = Field(default_factory=SyncCounts)
    error_code: Optional[str] = None
    error_message: Optional[str] = None


# =============================================================================
# Applied Mitigation Observation
# =============================================================================

class ApplyMitigationRequest(BaseModel):
    """POST /api/v1/memory/incidents/{incident_id}/mitigations request."""
    idempotency_key: str = Field(
        ...,
        min_length=1,
        description="Caller-supplied idempotency key for this application.",
    )
    description: str = Field(
        ...,
        min_length=1,
        description="Human-readable mitigation description.",
    )
    applied_at: datetime = Field(
        ...,
        description="When the mitigation was applied.",
    )
    recorded_by: str = Field(
        ...,
        min_length=1,
        description="Actor or system that recorded this application.",
    )
    notes: Optional[str] = Field(
        default=None,
        description="Optional bounded notes about the application.",
    )

    @field_validator("notes")
    @classmethod
    def truncate_notes(cls, v: Optional[str]) -> Optional[str]:
        """Truncate notes to a bounded length."""
        if v is not None and len(v) > 2000:
            return v[:2000]
        return v


class ApplyMitigationResponse(BaseModel):
    """POST /api/v1/memory/incidents/{incident_id}/mitigations response."""
    application_id: str
    incident_id: str
    mitigation_id: str
    description: str
    applied_at: datetime
    recorded_by: str
    notes: Optional[str] = None
    created: bool = Field(
        default=True,
        description="False if the idempotency key already existed.",
    )


# =============================================================================
# Outcome Observation
# =============================================================================

class RecordOutcomeRequest(BaseModel):
    """POST /api/v1/memory/incidents/{incident_id}/outcomes request."""
    idempotency_key: str = Field(
        ...,
        min_length=1,
        description="Caller-supplied idempotency key for this outcome.",
    )
    status: OutcomeStatus = Field(
        ...,
        description="Controlled outcome status.",
    )
    description: str = Field(
        ...,
        min_length=1,
        description="Bounded factual description of the outcome.",
    )
    observed_at: datetime = Field(
        ...,
        description="When the outcome was observed.",
    )
    recorded_by: str = Field(
        ...,
        min_length=1,
        description="Actor or system that recorded this outcome.",
    )
    mitigation_application_id: Optional[str] = Field(
        default=None,
        description=(
            "Optional reference to a mitigation application. "
            "Creates a temporal FOLLOWED_BY relationship, not a causal claim."
        ),
    )

    @field_validator("description")
    @classmethod
    def truncate_description(cls, v: str) -> str:
        """Truncate description to a bounded length."""
        if len(v) > 2000:
            return v[:2000]
        return v


class RecordOutcomeResponse(BaseModel):
    """POST /api/v1/memory/incidents/{incident_id}/outcomes response."""
    outcome_id: str
    incident_id: str
    scope: OutcomeScope
    status: OutcomeStatus
    description: str
    observed_at: datetime
    recorded_by: str
    mitigation_application_id: Optional[str] = None
    created: bool = Field(
        default=True,
        description="False if the idempotency key already existed.",
    )


# =============================================================================
# Query Response Models
# =============================================================================

class RootCauseInfo(BaseModel):
    """Root cause in a query response."""
    root_cause_id: str
    classification: str
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning_id: Optional[str] = None
    model: Optional[str] = None
    prompt_version: Optional[str] = None
    rationale: Optional[str] = None
    uncertainties: list[str] = Field(default_factory=list)
    source_phase: str = "phase5"


class MitigationInfo(BaseModel):
    """Mitigation in a query response."""
    mitigation_id: str
    description: str
    advisory_only: bool = True
    source: str


class AppliedMitigationInfo(BaseModel):
    """Applied mitigation in a query response."""
    application_id: str
    mitigation_id: str
    description: str
    applied_at: datetime
    recorded_by: str
    notes: Optional[str] = None


class OutcomeInfo(BaseModel):
    """Outcome in a query response."""
    outcome_id: str
    scope: OutcomeScope
    status: OutcomeStatus
    description: str
    observed_at: datetime
    recorded_by: str
    source: str


class IncidentMemoryResponse(BaseModel):
    """GET /api/v1/memory/incidents/{incident_id} response."""
    incident_id: str
    mission_id: str
    incident_type: str
    severity: str
    start_ms: int
    end_ms: int
    peak_risk: float
    phases: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    root_causes: list[RootCauseInfo] = Field(default_factory=list)
    recommended_mitigations: list[MitigationInfo] = Field(default_factory=list)
    applied_mitigations: list[AppliedMitigationInfo] = Field(default_factory=list)
    outcomes: list[OutcomeInfo] = Field(default_factory=list)
    source_phase: str = "phase4"
    synced_at: Optional[datetime] = None


class SimilarIncidentMatch(BaseModel):
    """Single match in a similar-history response."""
    incident_id: str
    mission_id: str
    incident_type: str
    severity: str
    start_ms: int
    end_ms: int
    peak_risk: float
    root_causes: list[RootCauseInfo] = Field(default_factory=list)
    recommended_mitigations: list[MitigationInfo] = Field(default_factory=list)
    applied_mitigations: list[AppliedMitigationInfo] = Field(default_factory=list)
    outcomes: list[OutcomeInfo] = Field(default_factory=list)


class SimilarHistoryResponse(BaseModel):
    """GET /api/v1/memory/incidents/{incident_id}/similar response."""
    query_incident_id: str
    matches: list[SimilarIncidentMatch] = Field(default_factory=list)
    total: int = 0


# =============================================================================
# Health
# =============================================================================

class HealthResponse(BaseModel):
    """GET /health response."""
    status: str = "ok"
    neo4j: str = "unavailable"
    schema_ready: bool = False
    phase2: str = "unknown"
    phase4: str = "unknown"
    phase5: str = "unknown"


# =============================================================================
# Graph Record Inputs (internal, used by mapper -> repository)
# =============================================================================

class MissionRecord(BaseModel):
    """Internal: mapped mission data ready for graph projection."""
    mission_id: str
    drone_id: str
    start_time: datetime
    end_time: Optional[datetime] = None
    mission_result: str
    source_phase: str = "phase2"
    source_updated_at: Optional[datetime] = None


class IncidentRecord(BaseModel):
    """Internal: mapped incident data ready for graph projection."""
    incident_id: str
    mission_id: str
    incident_type: str
    severity: str
    start_ms: int
    end_ms: int
    peak_risk: float = Field(ge=0.0, le=1.0)
    phases: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    source_phase: str = "phase4"


class RootCauseRecord(BaseModel):
    """Internal: mapped root cause data ready for graph projection."""
    root_cause_id: str
    classification: str
    normalized_classification: str
    source_phase: str = "phase5"


class MitigationRecord(BaseModel):
    """Internal: mapped mitigation data ready for graph projection."""
    mitigation_id: str
    description: str
    normalized_description: str
    advisory_only: bool = True
    source: str = "phase5_recommendation"


class AnalysisRelationship(BaseModel):
    """Internal: ANALYZED_AS relationship properties."""
    incident_id: str
    root_cause_id: str
    reasoning_id: str
    confidence: float = Field(ge=0.0, le=1.0)
    model: str
    prompt_version: str
    rationale: str
    uncertainties: list[str] = Field(default_factory=list)
    created_at: str
    phoenix_trace_id: Optional[str] = None


class RecommendationRelationship(BaseModel):
    """Internal: RECOMMENDED relationship properties."""
    incident_id: str
    mitigation_id: str
    reasoning_id: str
    recommended_at: str
    advisory_only: bool = True


class OutcomeRecord(BaseModel):
    """Internal: mapped outcome data ready for graph projection."""
    outcome_id: str
    scope: str
    status: str
    description: str
    observed_at: datetime
    source: str
    recorded_by: str


class MissionProjection(BaseModel):
    """Internal: complete projection for one mission sync transaction."""
    mission: MissionRecord
    incidents: list[IncidentRecord] = Field(default_factory=list)
    root_causes: list[RootCauseRecord] = Field(default_factory=list)
    mitigations: list[MitigationRecord] = Field(default_factory=list)
    analyses: list[AnalysisRelationship] = Field(default_factory=list)
    recommendations: list[RecommendationRelationship] = Field(default_factory=list)
    outcomes: list[OutcomeRecord] = Field(default_factory=list)
    mission_outcome: Optional[OutcomeRecord] = None
