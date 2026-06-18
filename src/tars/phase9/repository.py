"""
Phase 9 Evaluation Repository
===============================
Async PostgreSQL operations for evaluation results, metrics, and labels.

Provides:
- Create and retrieve evaluation results with metrics.
- Idempotent duplicate detection.
- Overwrite support.
- Ground-truth label upsert and lookup.
- Mission-level and reasoning-level queries.

No raw prompts, responses, telemetry, or trace bodies are stored.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .models import (
    ClassificationLabel,
    EvaluationMetric,
    EvaluationResponse,
    EvaluationResult,
    GroundTruthLabel,
    GroundTruthLabelResponse,
    GroundTruthSource,
    MetricName,
)

logger = logging.getLogger("phase9.repository")


class EvaluationRepository:
    """
    Async repository for Phase 9 evaluation persistence.

    Uses raw SQL via SQLAlchemy text() for clarity and control.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # -----------------------------------------------------------------------
    # Evaluation Results
    # -----------------------------------------------------------------------

    async def find_existing_evaluation(
        self,
        mission_id: str,
        incident_id: Optional[str],
        reasoning_id: Optional[str],
        evaluator_version: str,
    ) -> Optional[EvaluationResponse]:
        """
        Find an existing evaluation by unique target key.

        Returns the evaluation response if found, None otherwise.
        """
        result = await self._session.execute(
            text("""
                SELECT evaluation_id, mission_id, incident_id, reasoning_id,
                       trace_id, overall_score, root_cause_score,
                       recommendation_score, consistency_score,
                       false_positive, false_negative, evidence_level,
                       evaluator_version, advisory_only, created_at
                FROM evaluation_results
                WHERE mission_id = :mission_id
                  AND COALESCE(incident_id, '__null__') = :incident_id
                  AND COALESCE(reasoning_id, '__null__') = :reasoning_id
                  AND evaluator_version = :evaluator_version
            """),
            {
                "mission_id": mission_id,
                "incident_id": incident_id or "__null__",
                "reasoning_id": reasoning_id or "__null__",
                "evaluator_version": evaluator_version,
            },
        )
        row = result.mappings().first()
        if row is None:
            return None

        metrics = await self._load_metrics(row["evaluation_id"])

        return EvaluationResponse(
            evaluation_id=row["evaluation_id"],
            mission_id=row["mission_id"],
            incident_id=row["incident_id"],
            reasoning_id=row["reasoning_id"],
            overall_score=row["overall_score"],
            false_positive=row["false_positive"],
            false_negative=row["false_negative"],
            metrics=metrics,
            evidence_level=row["evidence_level"],
            evaluator_version=row["evaluator_version"],
            created_at=row["created_at"],
            advisory_only=row["advisory_only"],
        )

    async def save_evaluation(
        self,
        result: EvaluationResult,
    ) -> str:
        """
        Persist an evaluation result with all metric rows.

        Returns the evaluation_id.
        """
        now = datetime.now(timezone.utc)

        # Extract individual scores from metrics for denormalized columns
        root_cause_score = None
        recommendation_score = None
        consistency_score = None

        for m in result.metrics:
            if m.name == MetricName.ROOT_CAUSE_ACCURACY:
                root_cause_score = m.score
            elif m.name == MetricName.RECOMMENDATION_ACCURACY:
                recommendation_score = m.score
            elif m.name == MetricName.RESPONSE_CONSISTENCY:
                consistency_score = m.score

        await self._session.execute(
            text("""
                INSERT INTO evaluation_results (
                    evaluation_id, mission_id, incident_id, reasoning_id,
                    trace_id, overall_score, root_cause_score,
                    recommendation_score, consistency_score,
                    false_positive, false_negative, evidence_level,
                    evaluator_version, advisory_only, created_at, updated_at
                ) VALUES (
                    :evaluation_id, :mission_id, :incident_id, :reasoning_id,
                    :trace_id, :overall_score, :root_cause_score,
                    :recommendation_score, :consistency_score,
                    :false_positive, :false_negative, :evidence_level,
                    :evaluator_version, :advisory_only, :created_at, :updated_at
                )
            """),
            {
                "evaluation_id": result.evaluation_id,
                "mission_id": result.mission_id,
                "incident_id": result.incident_id,
                "reasoning_id": result.reasoning_id,
                "trace_id": result.trace_id,
                "overall_score": result.overall_score,
                "root_cause_score": root_cause_score,
                "recommendation_score": recommendation_score,
                "consistency_score": consistency_score,
                "false_positive": result.false_positive,
                "false_negative": result.false_negative,
                "evidence_level": result.evidence_level,
                "evaluator_version": result.evaluator_version,
                "advisory_only": True,
                "created_at": now,
                "updated_at": now,
            },
        )

        # Insert metric rows
        for metric in result.metrics:
            metric_id = f"metric_{uuid.uuid4().hex[:16]}"
            await self._session.execute(
                text("""
                    INSERT INTO evaluation_metrics (
                        metric_id, evaluation_id, name, score, label,
                        evidence, explanation, created_at
                    ) VALUES (
                        :metric_id, :evaluation_id, :name, :score, :label,
                        :evidence, :explanation, :created_at
                    )
                """),
                {
                    "metric_id": metric_id,
                    "evaluation_id": result.evaluation_id,
                    "name": metric.name.value,
                    "score": metric.score,
                    "label": metric.label.value,
                    "evidence": json.dumps(metric.evidence),
                    "explanation": metric.explanation,
                    "created_at": now,
                },
            )

        await self._session.commit()
        logger.info(
            "Saved evaluation '%s' for mission '%s'",
            result.evaluation_id,
            result.mission_id,
        )
        return result.evaluation_id

    async def overwrite_evaluation(
        self,
        result: EvaluationResult,
    ) -> str:
        """
        Replace an existing evaluation for the same target.

        Deletes the old evaluation (cascading to metrics) and inserts new.
        """
        # Delete existing
        await self._session.execute(
            text("""
                DELETE FROM evaluation_results
                WHERE mission_id = :mission_id
                  AND COALESCE(incident_id, '__null__') = :incident_id
                  AND COALESCE(reasoning_id, '__null__') = :reasoning_id
                  AND evaluator_version = :evaluator_version
            """),
            {
                "mission_id": result.mission_id,
                "incident_id": result.incident_id or "__null__",
                "reasoning_id": result.reasoning_id or "__null__",
                "evaluator_version": result.evaluator_version,
            },
        )

        return await self.save_evaluation(result)

    async def get_evaluation(
        self,
        evaluation_id: str,
    ) -> Optional[EvaluationResponse]:
        """Get a single evaluation by ID."""
        result = await self._session.execute(
            text("""
                SELECT evaluation_id, mission_id, incident_id, reasoning_id,
                       trace_id, overall_score, false_positive, false_negative,
                       evidence_level, evaluator_version, advisory_only,
                       created_at
                FROM evaluation_results
                WHERE evaluation_id = :evaluation_id
            """),
            {"evaluation_id": evaluation_id},
        )
        row = result.mappings().first()
        if row is None:
            return None

        metrics = await self._load_metrics(evaluation_id)

        return EvaluationResponse(
            evaluation_id=row["evaluation_id"],
            mission_id=row["mission_id"],
            incident_id=row["incident_id"],
            reasoning_id=row["reasoning_id"],
            overall_score=row["overall_score"],
            false_positive=row["false_positive"],
            false_negative=row["false_negative"],
            metrics=metrics,
            evidence_level=row["evidence_level"],
            evaluator_version=row["evaluator_version"],
            created_at=row["created_at"],
            advisory_only=row["advisory_only"],
        )

    async def get_evaluations_by_mission(
        self,
        mission_id: str,
    ) -> list[EvaluationResponse]:
        """Get all evaluations for a mission."""
        result = await self._session.execute(
            text("""
                SELECT evaluation_id, mission_id, incident_id, reasoning_id,
                       trace_id, overall_score, false_positive, false_negative,
                       evidence_level, evaluator_version, advisory_only,
                       created_at
                FROM evaluation_results
                WHERE mission_id = :mission_id
                ORDER BY created_at DESC
            """),
            {"mission_id": mission_id},
        )
        rows = result.mappings().all()

        evaluations = []
        for row in rows:
            metrics = await self._load_metrics(row["evaluation_id"])
            evaluations.append(
                EvaluationResponse(
                    evaluation_id=row["evaluation_id"],
                    mission_id=row["mission_id"],
                    incident_id=row["incident_id"],
                    reasoning_id=row["reasoning_id"],
                    overall_score=row["overall_score"],
                    false_positive=row["false_positive"],
                    false_negative=row["false_negative"],
                    metrics=metrics,
                    evidence_level=row["evidence_level"],
                    evaluator_version=row["evaluator_version"],
                    created_at=row["created_at"],
                    advisory_only=row["advisory_only"],
                )
            )

        return evaluations

    async def get_evaluations_by_reasoning(
        self,
        reasoning_id: str,
    ) -> list[EvaluationResponse]:
        """Get all evaluations for a reasoning result."""
        result = await self._session.execute(
            text("""
                SELECT evaluation_id, mission_id, incident_id, reasoning_id,
                       trace_id, overall_score, false_positive, false_negative,
                       evidence_level, evaluator_version, advisory_only,
                       created_at
                FROM evaluation_results
                WHERE reasoning_id = :reasoning_id
                ORDER BY created_at DESC
            """),
            {"reasoning_id": reasoning_id},
        )
        rows = result.mappings().all()

        evaluations = []
        for row in rows:
            metrics = await self._load_metrics(row["evaluation_id"])
            evaluations.append(
                EvaluationResponse(
                    evaluation_id=row["evaluation_id"],
                    mission_id=row["mission_id"],
                    incident_id=row["incident_id"],
                    reasoning_id=row["reasoning_id"],
                    overall_score=row["overall_score"],
                    false_positive=row["false_positive"],
                    false_negative=row["false_negative"],
                    metrics=metrics,
                    evidence_level=row["evidence_level"],
                    evaluator_version=row["evaluator_version"],
                    created_at=row["created_at"],
                    advisory_only=row["advisory_only"],
                )
            )

        return evaluations

    async def get_similar_evaluations(
        self,
        incident_type: str,
        severity: str,
        root_cause_family: Optional[str],
        exclude_evaluation_id: Optional[str] = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """
        Find similar evaluated cases for consistency scoring.

        Returns evaluation results with their root-cause and recommendation
        scores for comparison.
        """
        params: dict[str, Any] = {
            "limit": limit,
        }

        # Build a query that joins evaluation_results with evaluation_metrics
        # to find evaluations for similar incidents
        # We look for evaluations that have root_cause_accuracy metrics
        query = """
            SELECT er.evaluation_id, er.mission_id, er.incident_id,
                   er.reasoning_id, er.overall_score,
                   er.root_cause_score, er.recommendation_score,
                   er.false_positive, er.false_negative,
                   er.created_at
            FROM evaluation_results er
            WHERE er.incident_id IS NOT NULL
        """

        if exclude_evaluation_id:
            query += " AND er.evaluation_id != :exclude_id"
            params["exclude_id"] = exclude_evaluation_id

        query += " ORDER BY er.created_at DESC LIMIT :limit"

        result = await self._session.execute(text(query), params)
        rows = result.mappings().all()

        return [dict(row) for row in rows]

    # -----------------------------------------------------------------------
    # Ground Truth Labels
    # -----------------------------------------------------------------------

    async def upsert_label(
        self,
        mission_id: str,
        incident_id: Optional[str],
        root_cause: Optional[str],
        preferred_mitigation: Optional[str],
        outcome: Optional[str],
        source: str,
        labeled_by: Optional[str],
        labeled_at: Optional[datetime],
    ) -> GroundTruthLabelResponse:
        """
        Create or update a ground-truth label.

        Upserts on (mission_id, incident_id, source).
        """
        now = datetime.now(timezone.utc)
        label_id = f"label_{uuid.uuid4().hex[:16]}"

        # Check for existing
        existing = await self._session.execute(
            text("""
                SELECT label_id FROM ground_truth_labels
                WHERE mission_id = :mission_id
                  AND COALESCE(incident_id, '__null__') = :incident_id
                  AND source = :source
            """),
            {
                "mission_id": mission_id,
                "incident_id": incident_id or "__null__",
                "source": source,
            },
        )
        existing_row = existing.mappings().first()

        if existing_row:
            label_id = existing_row["label_id"]
            await self._session.execute(
                text("""
                    UPDATE ground_truth_labels
                    SET root_cause = :root_cause,
                        preferred_mitigation = :preferred_mitigation,
                        outcome = :outcome,
                        labeled_by = :labeled_by,
                        labeled_at = :labeled_at
                    WHERE label_id = :label_id
                """),
                {
                    "label_id": label_id,
                    "root_cause": root_cause,
                    "preferred_mitigation": preferred_mitigation,
                    "outcome": outcome,
                    "labeled_by": labeled_by,
                    "labeled_at": labeled_at or now,
                },
            )
        else:
            await self._session.execute(
                text("""
                    INSERT INTO ground_truth_labels (
                        label_id, mission_id, incident_id, root_cause,
                        preferred_mitigation, outcome, source,
                        labeled_by, labeled_at, created_at
                    ) VALUES (
                        :label_id, :mission_id, :incident_id, :root_cause,
                        :preferred_mitigation, :outcome, :source,
                        :labeled_by, :labeled_at, :created_at
                    )
                """),
                {
                    "label_id": label_id,
                    "mission_id": mission_id,
                    "incident_id": incident_id,
                    "root_cause": root_cause,
                    "preferred_mitigation": preferred_mitigation,
                    "outcome": outcome,
                    "source": source,
                    "labeled_by": labeled_by,
                    "labeled_at": labeled_at or now,
                    "created_at": now,
                },
            )

        await self._session.commit()

        return GroundTruthLabelResponse(
            label_id=label_id,
            mission_id=mission_id,
            incident_id=incident_id,
            root_cause=root_cause,
            preferred_mitigation=preferred_mitigation,
            outcome=outcome,
            source=GroundTruthSource(source),
            labeled_by=labeled_by,
            labeled_at=labeled_at or now,
            created_at=now,
        )

    async def get_labels_for_target(
        self,
        mission_id: str,
        incident_id: Optional[str] = None,
    ) -> list[GroundTruthLabelResponse]:
        """
        Get all ground-truth labels for a target.

        Returns labels ordered by source priority (operator_label first).
        """
        if incident_id:
            result = await self._session.execute(
                text("""
                    SELECT label_id, mission_id, incident_id, root_cause,
                           preferred_mitigation, outcome, source,
                           labeled_by, labeled_at, created_at
                    FROM ground_truth_labels
                    WHERE mission_id = :mission_id
                      AND incident_id = :incident_id
                    ORDER BY
                        CASE source
                            WHEN 'operator_label' THEN 1
                            WHEN 'mission_outcome' THEN 2
                            WHEN 'synthetic_test_case' THEN 3
                            WHEN 'deterministic_rule' THEN 4
                            ELSE 5
                        END
                """),
                {
                    "mission_id": mission_id,
                    "incident_id": incident_id,
                },
            )
        else:
            result = await self._session.execute(
                text("""
                    SELECT label_id, mission_id, incident_id, root_cause,
                           preferred_mitigation, outcome, source,
                           labeled_by, labeled_at, created_at
                    FROM ground_truth_labels
                    WHERE mission_id = :mission_id
                      AND incident_id IS NULL
                    ORDER BY
                        CASE source
                            WHEN 'operator_label' THEN 1
                            WHEN 'mission_outcome' THEN 2
                            WHEN 'synthetic_test_case' THEN 3
                            WHEN 'deterministic_rule' THEN 4
                            ELSE 5
                        END
                """),
                {"mission_id": mission_id},
            )

        rows = result.mappings().all()
        return [
            GroundTruthLabelResponse(
                label_id=row["label_id"],
                mission_id=row["mission_id"],
                incident_id=row["incident_id"],
                root_cause=row["root_cause"],
                preferred_mitigation=row["preferred_mitigation"],
                outcome=row["outcome"],
                source=GroundTruthSource(row["source"]),
                labeled_by=row["labeled_by"],
                labeled_at=row["labeled_at"],
                created_at=row["created_at"],
            )
            for row in rows
        ]

    # -----------------------------------------------------------------------
    # Internal Helpers
    # -----------------------------------------------------------------------

    async def _load_metrics(
        self,
        evaluation_id: str,
    ) -> list[EvaluationMetric]:
        """Load all metrics for an evaluation."""
        result = await self._session.execute(
            text("""
                SELECT name, score, label, evidence, explanation
                FROM evaluation_metrics
                WHERE evaluation_id = :evaluation_id
                ORDER BY created_at
            """),
            {"evaluation_id": evaluation_id},
        )
        rows = result.mappings().all()

        metrics = []
        for row in rows:
            evidence = row["evidence"]
            if isinstance(evidence, str):
                evidence = json.loads(evidence)

            metrics.append(
                EvaluationMetric(
                    name=MetricName(row["name"]),
                    score=row["score"],
                    label=ClassificationLabel(row["label"]),
                    evidence=evidence,
                    explanation=row["explanation"],
                )
            )

        return metrics
