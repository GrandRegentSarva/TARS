"""create phase 10 learning tables

Revision ID: 010
Revises: 009
Create Date: 2026-06-21

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "010"
down_revision: Union[str, None] = "009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # learning_runs
    # ------------------------------------------------------------------
    op.create_table(
        "learning_runs",
        sa.Column("run_id", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column(
            "filters_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("learning_version", sa.String(), nullable=False),
        sa.Column(
            "evaluated_cases_read", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "evidence_items_used", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "candidates_proposed", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "candidates_updated", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "candidates_suppressed", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "warnings_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
        sa.Column("dry_run", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("run_id"),
    )
    op.create_index(
        "ix_learning_runs_status",
        "learning_runs",
        ["status"],
    )
    op.create_index(
        "ix_learning_runs_started_at",
        "learning_runs",
        ["started_at"],
    )

    # ------------------------------------------------------------------
    # candidate_knowledge
    # ------------------------------------------------------------------
    op.create_table(
        "candidate_knowledge",
        sa.Column("candidate_id", sa.String(), nullable=False),
        sa.Column("candidate_type", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="proposed"),
        sa.Column("statement", sa.Text(), nullable=False),
        sa.Column("incident_family", sa.String(), nullable=True),
        sa.Column("root_cause", sa.String(), nullable=True),
        sa.Column("mitigation", sa.String(), nullable=True),
        sa.Column("outcome_family", sa.String(), nullable=True),
        sa.Column(
            "support_count", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "contradiction_count", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "distinct_mission_count", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "success_rate", sa.Float(), nullable=False, server_default="0.0"
        ),
        sa.Column("mean_overall_score", sa.Float(), nullable=True),
        sa.Column(
            "confidence", sa.Float(), nullable=False, server_default="0.0"
        ),
        sa.Column("learning_version", sa.String(), nullable=False),
        sa.Column("dedupe_key", sa.String(), nullable=False),
        sa.Column("supersedes_candidate_id", sa.String(), nullable=True),
        sa.Column(
            "advisory_only", sa.Boolean(), nullable=False, server_default="true"
        ),
        sa.Column("retire_reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("candidate_id"),
    )
    # Unique index on dedupe_key + learning_version for active candidates
    op.execute(
        """
        CREATE UNIQUE INDEX ix_candidate_knowledge_dedupe_active
        ON candidate_knowledge (dedupe_key, learning_version)
        WHERE status = 'proposed'
        """
    )
    op.create_index(
        "ix_candidate_knowledge_candidate_type",
        "candidate_knowledge",
        ["candidate_type"],
    )
    op.create_index(
        "ix_candidate_knowledge_incident_family",
        "candidate_knowledge",
        ["incident_family"],
    )
    op.create_index(
        "ix_candidate_knowledge_root_cause",
        "candidate_knowledge",
        ["root_cause"],
    )
    op.create_index(
        "ix_candidate_knowledge_confidence",
        "candidate_knowledge",
        ["confidence"],
    )
    op.create_index(
        "ix_candidate_knowledge_status",
        "candidate_knowledge",
        ["status"],
    )

    # ------------------------------------------------------------------
    # candidate_evidence
    # ------------------------------------------------------------------
    op.create_table(
        "candidate_evidence",
        sa.Column("evidence_id", sa.String(), nullable=False),
        sa.Column("candidate_id", sa.String(), nullable=False),
        sa.Column("mission_id", sa.String(), nullable=False),
        sa.Column("incident_id", sa.String(), nullable=True),
        sa.Column("reasoning_id", sa.String(), nullable=True),
        sa.Column("evaluation_id", sa.String(), nullable=True),
        sa.Column("trace_id", sa.String(), nullable=True),
        sa.Column("root_cause", sa.String(), nullable=True),
        sa.Column("mitigation", sa.String(), nullable=True),
        sa.Column("outcome", sa.String(), nullable=True),
        sa.Column("overall_score", sa.Float(), nullable=True),
        sa.Column(
            "metric_labels_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "evidence_levels_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["candidate_id"],
            ["candidate_knowledge.candidate_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("evidence_id"),
    )
    op.create_index(
        "ix_candidate_evidence_candidate_id",
        "candidate_evidence",
        ["candidate_id"],
    )
    op.create_index(
        "ix_candidate_evidence_mission_id",
        "candidate_evidence",
        ["mission_id"],
    )
    op.create_index(
        "ix_candidate_evidence_incident_id",
        "candidate_evidence",
        ["incident_id"],
    )
    op.create_index(
        "ix_candidate_evidence_evaluation_id",
        "candidate_evidence",
        ["evaluation_id"],
    )
    op.create_index(
        "ix_candidate_evidence_trace_id",
        "candidate_evidence",
        ["trace_id"],
    )

    # ------------------------------------------------------------------
    # learning_run_candidates
    # ------------------------------------------------------------------
    op.create_table(
        "learning_run_candidates",
        sa.Column("run_id", sa.String(), nullable=False),
        sa.Column("candidate_id", sa.String(), nullable=False),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["learning_runs.run_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["candidate_id"],
            ["candidate_knowledge.candidate_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("run_id", "candidate_id"),
    )


def downgrade() -> None:
    op.drop_table("learning_run_candidates")
    op.drop_table("candidate_evidence")
    op.drop_table("candidate_knowledge")
    op.drop_table("learning_runs")
