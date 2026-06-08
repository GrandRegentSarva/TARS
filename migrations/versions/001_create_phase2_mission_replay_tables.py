"""create phase 2 mission replay tables

Revision ID: 001
Revises: None
Create Date: 2026-06-08

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # missions
    # ------------------------------------------------------------------
    op.create_table(
        "missions",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("mission_id", sa.String(), nullable=False),
        sa.Column("drone_id", sa.String(), nullable=False),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("mission_result", sa.String(), nullable=False),
        sa.Column("summary", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("source_file", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("mission_id"),
    )
    op.create_index("ix_missions_mission_id", "missions", ["mission_id"])

    # ------------------------------------------------------------------
    # telemetry_events
    # ------------------------------------------------------------------
    op.create_table(
        "telemetry_events",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("mission_id", sa.String(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("elapsed_ms", sa.Integer(), nullable=False),
        sa.Column("position", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("velocity", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("battery", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("gps", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("attitude", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("flight_mode", sa.String(), nullable=True),
        sa.Column("health", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("raw", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(
            ["mission_id"],
            ["missions.mission_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_telemetry_events_mission_sequence",
        "telemetry_events",
        ["mission_id", "sequence"],
    )
    op.create_index(
        "ix_telemetry_events_mission_timestamp",
        "telemetry_events",
        ["mission_id", "timestamp"],
    )
    op.create_index(
        "ix_telemetry_events_timestamp",
        "telemetry_events",
        ["timestamp"],
    )

    # ------------------------------------------------------------------
    # fault_events
    # ------------------------------------------------------------------
    op.create_table(
        "fault_events",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("mission_id", sa.String(), nullable=False),
        sa.Column("fault_type", sa.String(), nullable=False),
        sa.Column("triggered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("elapsed_ms", sa.Integer(), nullable=True),
        sa.Column("parameters", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["mission_id"],
            ["missions.mission_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_fault_events_mission_triggered",
        "fault_events",
        ["mission_id", "triggered_at"],
    )
    op.create_index(
        "ix_fault_events_mission_type",
        "fault_events",
        ["mission_id", "fault_type"],
    )


def downgrade() -> None:
    op.drop_table("fault_events")
    op.drop_table("telemetry_events")
    op.drop_index("ix_missions_mission_id", table_name="missions")
    op.drop_table("missions")
