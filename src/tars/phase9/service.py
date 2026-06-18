"""
Phase 9 Evaluation Service
============================
Orchestrates evaluation of reasoning results against ground truth.

Responsibilities:
- Load reasoning results from Phase 5 adapters.
- Load incident facts from Phase 4 when needed.
- Load ground-truth labels from multiple sources.
- Run the deterministic evaluator.
- Persist evaluation results.
- Optionally export to Phoenix.
- Handle fail-open behavior for optional dependencies.

The service never invokes Gemini, mutates upstream records, or calls
flight-control APIs.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from .config import settings
from .evaluator import Evaluator
from .ground_truth import GroundTruthLoader, GroundTruthResult
from .models import (
    BatchEvaluationResponse,
    BatchItemResult,
    ClassificationLabel,
    EvaluationMetric,
    EvaluationRequest,
    EvaluationResponse,
    EvaluationResult,
    MetricName,
)
from .phoenix_exporter import PhoenixEvalExporter
from .repository import EvaluationRepository

logger = logging.getLogger("phase9.service")


class EvaluationService:
    """
    Service layer for Phase 9 evaluation.

    Coordinates adapters, ground-truth loading, scoring, persistence,
    and optional Phoenix export.
    """

    def __init__(
        self,
        repository: EvaluationRepository,
        ground_truth_loader: GroundTruthLoader,
        evaluator: Optional[Evaluator] = None,
        phoenix_exporter: Optional[PhoenixEvalExporter] = None,
        phase4_client: Any = None,
        phase5_client: Any = None,
    ) -> None:
        self._repository = repository
        self._ground_truth_loader = ground_truth_loader
        self._evaluator = evaluator or Evaluator()
        self._phoenix_exporter = phoenix_exporter or PhoenixEvalExporter()
        self._phase4_client = phase4_client
        self._phase5_client = phase5_client

    async def evaluate(
        self,
        request: EvaluationRequest,
    ) -> EvaluationResponse:
        """
        Evaluate one reasoning result or mission-level target.

        Steps:
        1. Check for existing evaluation (idempotency).
        2. Load reasoning result from Phase 5.
        3. Load ground-truth labels.
        4. Run evaluator.
        5. Persist result.
        6. Optionally export to Phoenix.

        Args:
            request: Evaluation request.

        Returns:
            EvaluationResponse with scores and metrics.

        Raises:
            ValueError: On validation errors.
            RuntimeError: On store unavailability.
        """
        # 1. Check for existing evaluation
        if not request.overwrite:
            existing = await self._repository.find_existing_evaluation(
                mission_id=request.mission_id,
                incident_id=request.incident_id,
                reasoning_id=request.reasoning_id,
                evaluator_version=settings.EVALUATION_VERSION,
            )
            if existing is not None:
                return existing

        # 2. Load reasoning result
        reasoning = await self._load_reasoning(request)

        # 3. Load incident facts (optional)
        incident = await self._load_incident(request)

        # 4. Load ground truth
        ground_truth = await self._ground_truth_loader.resolve(
            mission_id=request.mission_id,
            incident_id=request.incident_id,
            reasoning_id=request.reasoning_id,
            request_ground_truth=request.ground_truth,
        )

        # 5. Run evaluator
        metrics = self._evaluator.evaluate(
            reasoning=reasoning,
            ground_truth=ground_truth,
            incident=incident,
            similar_evaluations=await self._load_similar_evaluations(request),
            evaluate_consistency=request.evaluate_consistency,
        )

        # 5b. False-negative scoring (mission-level)
        fn_metric = await self._evaluate_false_negative(
            request, ground_truth
        )
        if fn_metric is not None:
            metrics.append(fn_metric)

        # Compute overall score
        overall_score = self._evaluator.compute_overall_score(metrics)

        # Determine false positive/negative from metrics
        false_positive = any(
            m.name == MetricName.FALSE_POSITIVE
            and m.label == ClassificationLabel.INCORRECT
            for m in metrics
        )
        false_negative = any(
            m.name == MetricName.FALSE_NEGATIVE
            and m.label == ClassificationLabel.INCORRECT
            for m in metrics
        )

        # Determine strongest evidence level
        evidence_level = ground_truth.evidence_level

        # Build result
        evaluation_id = f"eval_{uuid.uuid4().hex[:16]}"
        now = datetime.now(timezone.utc)

        result = EvaluationResult(
            evaluation_id=evaluation_id,
            mission_id=request.mission_id,
            incident_id=request.incident_id,
            reasoning_id=request.reasoning_id,
            trace_id=request.trace_id,
            metrics=metrics,
            overall_score=overall_score,
            false_positive=false_positive,
            false_negative=false_negative,
            evidence_level=evidence_level,
            evaluator_version=settings.EVALUATION_VERSION,
            created_at=now,
            advisory_only=True,
        )

        # 6. Persist
        try:
            if request.overwrite:
                await self._repository.overwrite_evaluation(result)
            else:
                await self._repository.save_evaluation(result)
        except Exception as exc:
            logger.error(
                "Failed to persist evaluation '%s': %s",
                evaluation_id,
                exc,
            )
            raise RuntimeError(
                f"Failed to persist evaluation: {exc}"
            ) from exc

        # 7. Optional Phoenix export (fail-open)
        if self._phoenix_exporter.is_enabled:
            try:
                await self._phoenix_exporter.export_evaluation(result)
            except Exception as exc:
                logger.warning(
                    "Phoenix export failed for '%s': %s",
                    evaluation_id,
                    exc,
                )

        return EvaluationResponse(
            evaluation_id=result.evaluation_id,
            mission_id=result.mission_id,
            incident_id=result.incident_id,
            reasoning_id=result.reasoning_id,
            overall_score=result.overall_score,
            false_positive=result.false_positive,
            false_negative=result.false_negative,
            metrics=result.metrics,
            evidence_level=result.evidence_level,
            evaluator_version=result.evaluator_version,
            created_at=result.created_at,
            advisory_only=True,
        )

    async def evaluate_batch(
        self,
        targets: list[EvaluationRequest],
    ) -> BatchEvaluationResponse:
        """
        Evaluate a bounded list of targets.

        Partial failures are returned per item. A failed item does not
        abort successful evaluations.

        Args:
            targets: List of evaluation requests.

        Returns:
            BatchEvaluationResponse with per-item results.
        """
        results: list[BatchItemResult] = []
        succeeded = 0
        failed = 0

        for i, target in enumerate(targets):
            try:
                evaluation = await self.evaluate(target)
                results.append(
                    BatchItemResult(
                        index=i,
                        success=True,
                        evaluation=evaluation,
                    )
                )
                succeeded += 1
            except Exception as exc:
                logger.warning(
                    "Batch item %d failed: %s", i, exc
                )
                results.append(
                    BatchItemResult(
                        index=i,
                        success=False,
                        error=str(exc)[:500],
                    )
                )
                failed += 1

        return BatchEvaluationResponse(
            total=len(targets),
            succeeded=succeeded,
            failed=failed,
            results=results,
        )

    async def get_evaluation(
        self,
        evaluation_id: str,
    ) -> Optional[EvaluationResponse]:
        """Get a stored evaluation by ID."""
        return await self._repository.get_evaluation(evaluation_id)

    async def get_evaluations_by_mission(
        self,
        mission_id: str,
    ) -> list[EvaluationResponse]:
        """Get all evaluations for a mission."""
        return await self._repository.get_evaluations_by_mission(mission_id)

    async def get_evaluations_by_reasoning(
        self,
        reasoning_id: str,
    ) -> list[EvaluationResponse]:
        """Get all evaluations for a reasoning result."""
        return await self._repository.get_evaluations_by_reasoning(
            reasoning_id
        )

    # -----------------------------------------------------------------------
    # Internal Helpers
    # -----------------------------------------------------------------------

    async def _load_reasoning(
        self,
        request: EvaluationRequest,
    ) -> dict[str, Any]:
        """
        Load reasoning result from Phase 5.

        Returns a reasoning dict. Raises ValueError when a specific
        reasoning_id was requested but could not be found (Phase 5
        reachable but ID absent). Returns an empty reasoning dict
        only when Phase 5 is entirely unavailable or no reasoning_id
        was explicitly requested.
        """
        if self._phase5_client is None:
            if request.reasoning_id:
                raise ValueError(
                    f"Phase 5 client unavailable; cannot resolve "
                    f"reasoning_id='{request.reasoning_id}'"
                )
            return self._empty_reasoning(request)

        try:
            if request.reasoning_id and request.mission_id:
                result = await self._phase5_client.get_reasoning_by_id(
                    reasoning_id=request.reasoning_id,
                    mission_id=request.mission_id,
                )
                if result:
                    return result
                # Explicit reasoning_id requested but not found
                raise ValueError(
                    f"Reasoning '{request.reasoning_id}' not found "
                    f"for mission '{request.mission_id}'"
                )

            if request.incident_id and request.mission_id:
                result = await self._phase5_client.get_reasoning(
                    mission_id=request.mission_id,
                    incident_id=request.incident_id,
                )
                if result:
                    return result

        except ValueError:
            raise  # Re-raise ValueError for missing reasoning
        except Exception as exc:
            logger.warning(
                "Failed to load reasoning for mission='%s' "
                "incident='%s': %s",
                request.mission_id,
                request.incident_id,
                exc,
            )

        return self._empty_reasoning(request)

    async def _load_incident(
        self,
        request: EvaluationRequest,
    ) -> Optional[dict[str, Any]]:
        """Load incident facts from Phase 4."""
        if self._phase4_client is None or not request.incident_id:
            return None

        try:
            return await self._phase4_client.get_incident(
                mission_id=request.mission_id,
                incident_id=request.incident_id,
            )
        except Exception as exc:
            logger.warning(
                "Failed to load incident '%s': %s",
                request.incident_id,
                exc,
            )
            return None

    async def _load_similar_evaluations(
        self,
        request: EvaluationRequest,
    ) -> list[dict[str, Any]]:
        """Load similar evaluated cases for consistency scoring."""
        try:
            return await self._repository.get_similar_evaluations(
                incident_type="",  # Will match all for now
                severity="",
                root_cause_family=None,
                limit=settings.EVALUATION_SIMILARITY_LIMIT,
            )
        except Exception as exc:
            logger.warning(
                "Failed to load similar evaluations: %s", exc
            )
            return []

    async def _evaluate_false_negative(
        self,
        request: EvaluationRequest,
        ground_truth: "GroundTruthResult",
    ) -> Optional[EvaluationMetric]:
        """
        Run false-negative scoring at mission level.

        Loads all incidents and reasoning results for the mission,
        then delegates to the evaluator's score_false_negative().
        """
        if not ground_truth.has_evidence:
            return None

        # Load all incidents for the mission
        incidents: list[dict[str, Any]] = []
        if self._phase4_client is not None:
            try:
                incidents = await self._phase4_client.get_incidents(
                    request.mission_id
                )
            except Exception as exc:
                logger.warning(
                    "Failed to load incidents for FN scoring: %s", exc
                )

        # Load all reasoning results for the mission
        reasoning_results: list[dict[str, Any]] = []
        if self._phase5_client is not None:
            try:
                reasoning_results = await self._phase5_client.list_analyses(
                    request.mission_id
                )
            except Exception as exc:
                logger.warning(
                    "Failed to load reasoning results for FN scoring: %s",
                    exc,
                )

        return self._evaluator.score_false_negative(
            mission_id=request.mission_id,
            incidents=incidents,
            reasoning_results=reasoning_results,
            ground_truth=ground_truth,
        )

    def _empty_reasoning(
        self,
        request: EvaluationRequest,
    ) -> dict[str, Any]:
        """Create a minimal reasoning dict when no result is available."""
        return {
            "reasoning_id": request.reasoning_id or "",
            "mission_id": request.mission_id,
            "incident_id": request.incident_id or "",
            "root_cause": "",
            "recommendation": "",
            "confidence": 0.0,
            "rationale": "",
            "advisory_only": True,
        }
