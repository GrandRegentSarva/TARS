"""
Incident Engine Models
======================
Pydantic models for Phase 4 incident detection.

Defines:
- Enums for incident type, severity, and processing status
- Incident: the primary output of Phase 4
- RuleMatch: intermediate result from rule evaluation
- API request/response schemas
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# =============================================================================
# Enums
# =============================================================================

class IncidentType(str, Enum):
    """Classified incident types."""
    NAVIGATION_INSTABILITY = "navigation_instability"
    BATTERY_DEGRADATION = "battery_degradation"
    ATTITUDE_INSTABILITY = "attitude_instability"
    ALTITUDE_INSTABILITY = "altitude_instability"
    SENSOR_HEALTH_FAILURE = "sensor_health_failure"
    TELEMETRY_DEGRADATION = "telemetry_degradation"
    HIGH_RISK_STATE = "high_risk_state"


class Severity(str, Enum):
    """Incident severity levels."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ProcessingStatus(str, Enum):
    """Incident processing job status."""
    NOT_STARTED = "not_started"
    PROCESSING = "processing"
    COMPLETE = "complete"
    FAILED = "failed"


# =============================================================================
# Rule Match (intermediate)
# =============================================================================

class RuleMatch(BaseModel):
    """
    A single rule match against one state snapshot.

    Produced by the rule evaluator, consumed by the incident collapser.
    """
    incident_type: IncidentType
    severity: Severity
    sequence: int
    elapsed_ms: int
    phase: str
    evidence: list[str] = Field(default_factory=list)
    risk: float = 0.0


# =============================================================================
# Incident (primary output)
# =============================================================================

class Incident(BaseModel):
    """
    A bounded operational incident collapsed from multiple state matches.

    This is the primary output of Phase 4 -- a deterministic summary
    of a sustained operational problem during a mission.
    """
    incident_id: str
    mission_id: str
    incident_type: IncidentType
    severity: Severity
    start_sequence: int
    end_sequence: int
    start_ms: int
    end_ms: int
    contributing_states: int
    peak_risk: float = Field(default=0.0, ge=0.0, le=1.0)
    phases: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)


# =============================================================================
# API Request/Response Schemas
# =============================================================================

class HealthResponse(BaseModel):
    """GET /health response."""
    status: str = "ok"
    redis: str = "ok"


class ProcessRequest(BaseModel):
    """POST /api/v1/incidents/process/{mission_id} request body."""
    from_ms: int = Field(default=0, ge=0)
    to_ms: Optional[int] = Field(default=None, ge=0)
    overwrite: bool = Field(default=True)


class ProcessResponse(BaseModel):
    """POST /api/v1/incidents/process/{mission_id} response body."""
    mission_id: str
    states_evaluated: int
    incidents_detected: int
    status: str = "complete"


class IncidentListResponse(BaseModel):
    """GET /api/v1/incidents/{mission_id} response body."""
    mission_id: str
    incidents: list[Incident] = Field(default_factory=list)
    total: int = 0
    from_ms: int = 0
    to_ms: Optional[int] = None


class ProcessingStatusResponse(BaseModel):
    """GET /api/v1/incidents/{mission_id}/status response body."""
    mission_id: str
    status: ProcessingStatus = ProcessingStatus.NOT_STARTED
    states_evaluated: int = 0
    incidents_detected: int = 0
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    error: Optional[str] = None
