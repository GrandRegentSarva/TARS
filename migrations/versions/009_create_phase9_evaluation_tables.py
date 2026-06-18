"""create phase 9 evaluation tables

Revision ID: 009
Revises: 001
Create Date: 2026-06-18

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "009"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # evaluation_results
    # ------------------------------------------------------------------
    op.create_table(
        "evaluation_results",
        sa.Column("evaluation_id", sa.String(), nullable=False),
        sa.Column("mission_id", sa.String(), nullable=False),
        sa.Column("incident_id", sa.String(), nullable=True),
        sa.Column("reasoning_id", sa.String(), nullable=True),
        sa.Column("trace_id", sa.String(), nullable=True),
        sa.Column("overall_score", sa.Float(), nullable=True),
        sa.Column("root_cause_score", sa.Float(), nullable=True),
        sa.Column("recommendation_score", sa.Float(), nullable=True),
        sa.Column("consistency_score", sa.Float(), nullable=True),
        sa.Column("false_positive", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("false_negative", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("evidence_level", sa.String(), nullable=True),
        sa.Column("evaluator_version", sa.String(), nullable=False),
        sa.Column("advisory_only", sa.Boolean(), nullable=False, server_default="true"),
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
        sa.PrimaryKeyConstraint("evaluation_id"),
    )
    op.create_index(
        "ix_evaluation_results_mission_id",
        "evaluation_results",
        ["mission_id"],
    )
    op.create_index(
        "ix_evaluation_results_reasoning_id",
        "evaluation_results",
        ["reasoning_id"],
    )
    op.create_index(
        "ix_evaluation_results_incident_id",
        "evaluation_results",
        ["incident_id"],
    )
    # Uniqueness: mission_id + incident_id + reasoning_id + evaluator_version
    # NULLs are treated as distinct in PostgreSQL, so we use COALESCE
    op.execute(
        """
        CREATE UNIQUE INDEX ix_evaluation_results_unique_target
        ON evaluation_results (
            mission_id,
            COALESCE(incident_id, '__null__'),
            COALESCE(reasoning_id, '__null__'),
            evaluator_version
        )
        """
    )

    # ------------------------------------------------------------------
    # evaluation_metrics
    # ------------------------------------------------------------------
    op.create_table(
        "evaluation_metrics",
        sa.Column("metric_id", sa.String(), nullable=False),
        sa.Column("evaluation_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("label", sa.String(), nullable=False),
        sa.Column(
            "evidence",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["evaluation_id"],
            ["evaluation_results.evaluation_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("metric_id"),
    )
    op.create_index(
        "ix_evaluation_metrics_evaluation_id",
        "evaluation_metrics",
        ["evaluation_id"],
    )

    # ------------------------------------------------------------------
    # ground_truth_labels
    # ------------------------------------------------------------------
    op.create_table(
        "ground_truth_labels",
        sa.Column("label_id", sa.String(), nullable=False),
        sa.Column("mission_id", sa.String(), nullable=False),
        sa.Column("incident_id", sa.String(), nullable=True),
        sa.Column("root_cause", sa.String(), nullable=True),
        sa.Column("preferred_mitigation", sa.String(), nullable=True),
        sa.Column("outcome", sa.String(), nullable=True),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("labeled_by", sa.String(), nullable=True),
        sa.Column("labeled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("label_id"),
    )
    op.create_index(
        "ix_ground_truth_labels_mission_id",
        "ground_truth_labels",
        ["mission_id"],
    )
    op.create_index(
        "ix_ground_truth_labels_incident_id",
        "ground_truth_labels",
        ["incident_id"],
    )
    # Uniqueness: mission_id + incident_id + source
    op.execute(
        """
        CREATE UNIQUE INDEX ix_ground_truth_labels_unique_target
        ON ground_truth_labels (
            mission_id,
            COALESCE(incident_id, '__null__'),
            source
        )
        """
    )


def downgrade() -> None:
    op.drop_table("evaluation_metrics")
    op.drop_table("evaluation_results")
    op.drop_table("ground_truth_labels")
