"""
State Engine Models
===================
Pydantic models for Phase 3 state computation.

Defines:
- Enums for mission phase, health, and signal quality
- TelemetryFrame: input from Phase 2 replay
- StateSnapshot: computed state output
- API request/response schemas
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


# =============================================================================
# Enums
# =============================================================================

class MissionPhase(str, Enum):
    """Mission phase classification."""
    PREFLIGHT = "preflight"
    TAKEOFF = "takeoff"
    CLIMB = "climb"
    CRUISE = "cruise"
    RETURN_TO_LAUNCH = "return_to_launch"
    LANDING = "landing"
    LANDED = "landed"
    UNKNOWN = "unknown"


class HealthStatus(str, Enum):
    """Overall drone health assessment."""
    NOMINAL = "nominal"
    DEGRADED = "degraded"
    CRITICAL = "critical"
    UNKNOWN = "unknown"


class SignalQuality(str, Enum):
    """Signal quality indicator for individual subsystems."""
    NORMAL = "normal"
    WEAK = "weak"
    UNSTABLE = "unstable"
    MISSING = "missing"


class ProcessingStatus(str, Enum):
    """State processing job status."""
    NOT_STARTED = "not_started"
    PROCESSING = "processing"
    COMPLETE = "complete"
    PARTIAL = "partial"
    FAILED = "failed"


# =============================================================================
# Input Models (from Phase 2 replay)
# =============================================================================

class TelemetryFrame(BaseModel):
    """
    A single replay frame from Phase 2.

    Contains sequence number, timing, and the full telemetry payload
    as a nested dict matching the Phase 1 TelemetrySnapshot structure.
    """
    sequence: int
    elapsed_ms: int
    timestamp: datetime
    telemetry: dict[str, Any] = Field(default_factory=dict)


class ReplayData(BaseModel):
    """Phase 2 replay response containing ordered frames."""
    mission_id: str
    speed: float = 1.0
    from_ms: int = 0
    to_ms: Optional[int] = None
    total_frames: int = 0
    frames: list[TelemetryFrame] = Field(default_factory=list)


# =============================================================================
# State Output Models
# =============================================================================

class SignalIndicators(BaseModel):
    """Signal quality indicators for key subsystems."""
    gps_quality: SignalQuality = SignalQuality.NORMAL
    battery_level: SignalQuality = SignalQuality.NORMAL
    altitude_stability: SignalQuality = SignalQuality.NORMAL
    attitude_stability: SignalQuality = SignalQuality.NORMAL


class StateMetrics(BaseModel):
    """Derived numeric metrics from telemetry."""
    relative_altitude_m: Optional[float] = None
    ground_speed_m_s: Optional[float] = None
    battery_percent: Optional[float] = None
    gps_satellites: Optional[int] = None
    roll_abs_deg: Optional[float] = None
    pitch_abs_deg: Optional[float] = None


class StateSnapshot(BaseModel):
    """
    Computed state for a single point in time.

    This is the primary output of Phase 3 -- a deterministic summary
    of the drone's operational situation at a given moment.
    """
    mission_id: str
    sequence: int
    timestamp: datetime
    elapsed_ms: int
    phase: MissionPhase = MissionPhase.UNKNOWN
    health: HealthStatus = HealthStatus.UNKNOWN
    risk: float = Field(default=0.0, ge=0.0, le=1.0)
    signals: SignalIndicators = Field(default_factory=SignalIndicators)
    metrics: StateMetrics = Field(default_factory=StateMetrics)
    reasons: list[str] = Field(default_factory=list)


# =============================================================================
# API Request/Response Schemas
# =============================================================================

class HealthResponse(BaseModel):
    """GET /health response."""
    status: str = "ok"
    redis: str = "ok"


class ProcessRequest(BaseModel):
    """POST /api/v1/state/process/{mission_id} request body."""
    from_ms: int = Field(default=0, ge=0)
    to_ms: Optional[int] = Field(default=None, ge=0)
    speed: float = Field(default=1.0, gt=0.0, le=100.0)
    overwrite: bool = Field(default=True)


class ProcessResponse(BaseModel):
    """POST /api/v1/state/process/{mission_id} response body."""
    mission_id: str
    frames_processed: int
    frames_failed: int = 0
    states_written: int
    status: str = "complete"


class TimelineResponse(BaseModel):
    """GET /api/v1/state/{mission_id}/timeline response body."""
    mission_id: str
    states: list[StateSnapshot] = Field(default_factory=list)
    total: int = 0
    from_ms: int = 0
    to_ms: Optional[int] = None


class ProcessingStatusResponse(BaseModel):
    """GET /api/v1/state/{mission_id}/status response body."""
    mission_id: str
    status: ProcessingStatus = ProcessingStatus.NOT_STARTED
    frames_processed: int = 0
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    error: Optional[str] = None
