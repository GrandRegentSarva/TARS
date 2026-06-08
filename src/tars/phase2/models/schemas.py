"""
API Request/Response Schemas
============================
Pydantic models for the Phase 2 REST API boundary.

These are separate from the Phase 1 telemetry models (which define the
input contract) and from the SQLAlchemy ORM models (which define storage).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

class HealthResponse(BaseModel):
    """GET /health response."""
    status: str = "ok"
    database: str = "ok"


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------

class ImportRequest(BaseModel):
    """POST /missions/import request body."""
    path: str = Field(description="Path to Phase 1 mission JSON file")
    overwrite: bool = Field(default=False, description="Overwrite existing mission if duplicate")


class ImportResponse(BaseModel):
    """POST /missions/import response body."""
    mission_id: str
    events_imported: int
    faults_imported: int
    status: str = "imported"


# ---------------------------------------------------------------------------
# Mission Listing
# ---------------------------------------------------------------------------

class MissionSummarySchema(BaseModel):
    """Single mission in a list response (no telemetry arrays)."""
    mission_id: str
    drone_id: str
    start_time: datetime
    end_time: Optional[datetime] = None
    mission_result: str
    summary: Optional[dict[str, Any]] = None
    source_file: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class MissionListResponse(BaseModel):
    """GET /missions response."""
    missions: list[MissionSummarySchema]
    total: int
    limit: int
    offset: int


# ---------------------------------------------------------------------------
# Mission Detail
# ---------------------------------------------------------------------------

class FaultEventSchema(BaseModel):
    """Fault event within a mission detail response."""
    id: int
    fault_type: str
    triggered_at: datetime
    elapsed_ms: Optional[int] = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    description: str = ""

    model_config = {"from_attributes": True}


class MissionDetailResponse(BaseModel):
    """GET /missions/{mission_id} response."""
    mission_id: str
    drone_id: str
    start_time: datetime
    end_time: Optional[datetime] = None
    mission_result: str
    summary: Optional[dict[str, Any]] = None
    source_file: Optional[str] = None
    created_at: datetime
    faults: list[FaultEventSchema] = Field(default_factory=list)

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Mission Events
# ---------------------------------------------------------------------------

class MissionEventSchema(BaseModel):
    """Single telemetry event in an events response."""
    id: int
    sequence: int
    timestamp: datetime
    elapsed_ms: int
    position: Optional[dict[str, Any]] = None
    velocity: Optional[dict[str, Any]] = None
    battery: Optional[dict[str, Any]] = None
    gps: Optional[dict[str, Any]] = None
    attitude: Optional[dict[str, Any]] = None
    flight_mode: Optional[str] = None
    health: Optional[dict[str, Any]] = None
    raw: dict[str, Any] = Field(default_factory=dict)

    model_config = {"from_attributes": True}


class MissionEventResponse(BaseModel):
    """GET /missions/{mission_id}/events response."""
    mission_id: str
    events: list[MissionEventSchema]
    total: int
    limit: int
    offset: int


# ---------------------------------------------------------------------------
# Replay
# ---------------------------------------------------------------------------

class ReplayFrame(BaseModel):
    """Single frame in a replay response."""
    sequence: int
    elapsed_ms: int
    timestamp: datetime
    telemetry: dict[str, Any] = Field(default_factory=dict)


class ReplayResponse(BaseModel):
    """GET /missions/{mission_id}/replay response."""
    mission_id: str
    speed: float = 1.0
    from_ms: int = 0
    to_ms: Optional[int] = None
    total_frames: int = 0
    frames: list[ReplayFrame] = Field(default_factory=list)
