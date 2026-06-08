"""
ORM Table Definitions
=====================
SQLAlchemy declarative models for the Phase 2 mission replay store.

Tables:
- missions:          One row per imported mission.
- telemetry_events:  One row per telemetry snapshot within a mission.
- fault_events:      One row per fault injected during a mission.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    ForeignKey,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Shared declarative base for all Phase 2 ORM models."""
    pass


class Mission(Base):
    """
    A single imported mission record.

    Maps 1:1 to a Phase 1 output JSON file.
    """

    __tablename__ = "missions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    mission_id: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    drone_id: Mapped[str] = mapped_column(String, nullable=False)
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    mission_result: Mapped[str] = mapped_column(String, nullable=False, default="IN_PROGRESS")
    summary: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    source_file: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    # Relationships
    telemetry_events: Mapped[list[TelemetryEvent]] = relationship(
        "TelemetryEvent",
        back_populates="mission",
        cascade="all, delete-orphan",
        order_by="TelemetryEvent.sequence",
    )
    fault_events: Mapped[list[FaultEvent]] = relationship(
        "FaultEvent",
        back_populates="mission",
        cascade="all, delete-orphan",
        order_by="FaultEvent.triggered_at",
    )

    def __repr__(self) -> str:
        return f"<Mission {self.mission_id} [{self.mission_result}]>"


class TelemetryEvent(Base):
    """
    A single telemetry snapshot within a mission.

    Stores decomposed sensor payloads as JSONB columns for queryability,
    plus the full original snapshot in `raw` for forward compatibility.
    """

    __tablename__ = "telemetry_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    mission_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("missions.mission_id", ondelete="CASCADE"),
        nullable=False,
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    elapsed_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    position: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    velocity: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    battery: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    gps: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    attitude: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    flight_mode: Mapped[str | None] = mapped_column(String, nullable=True)
    health: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    raw: Mapped[dict] = mapped_column(JSONB, nullable=False)

    # Relationship
    mission: Mapped[Mission] = relationship("Mission", back_populates="telemetry_events")

    __table_args__ = (
        Index("ix_telemetry_events_mission_sequence", "mission_id", "sequence"),
        Index("ix_telemetry_events_mission_timestamp", "mission_id", "timestamp"),
        Index("ix_telemetry_events_timestamp", "timestamp"),
    )

    def __repr__(self) -> str:
        return f"<TelemetryEvent {self.mission_id}#{self.sequence}>"


class FaultEvent(Base):
    """
    A fault injected during a mission.

    Records fault type, timing, parameters, and a human-readable description.
    """

    __tablename__ = "fault_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    mission_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("missions.mission_id", ondelete="CASCADE"),
        nullable=False,
    )
    fault_type: Mapped[str] = mapped_column(String, nullable=False)
    triggered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    elapsed_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    parameters: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")

    # Relationship
    mission: Mapped[Mission] = relationship("Mission", back_populates="fault_events")

    __table_args__ = (
        Index("ix_fault_events_mission_triggered", "mission_id", "triggered_at"),
        Index("ix_fault_events_mission_type", "mission_id", "fault_type"),
    )

    def __repr__(self) -> str:
        return f"<FaultEvent {self.mission_id} {self.fault_type}>"
