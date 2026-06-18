"""
Phase 9 Phoenix Eval Exporter
===============================
Optionally exports evaluation scores and spans to Phoenix.

Phoenix is optional. Export failures do not fail evaluation persistence.
No full trace bodies are copied. Only evaluation metadata is exported.

Suggested span names:
- evaluation.evaluate
- evaluation.score_root_cause
- evaluation.score_recommendation
- evaluation.score_consistency
- evaluation.persist
- evaluation.export_phoenix

Suggested attributes:
- tars.evaluation.id
- tars.evaluation.version
- tars.evaluation.overall_score
- tars.evaluation.root_cause_score
- tars.evaluation.recommendation_score
- tars.evaluation.consistency_score
- tars.evaluation.false_positive
- tars.evaluation.false_negative
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from .config import settings
from .models import EvaluationResult, MetricName

logger = logging.getLogger("phase9.phoenix_exporter")


class PhoenixEvalExporter:
    """
    Optional Phoenix evaluation exporter.

    Exports evaluation scores as span attributes when Phoenix tracing
    is available and enabled. Never requires Phoenix for operation.
    """

    def __init__(self) -> None:
        self._tracer: Any = None
        self._enabled = settings.EVALUATION_EXPORT_PHOENIX

    def _get_tracer(self) -> Any:
        """Get or create the OpenTelemetry tracer."""
        if self._tracer is not None:
            return self._tracer

        if not self._enabled:
            return None

        try:
            from opentelemetry import trace

            self._tracer = trace.get_tracer(
                "tars.phase9.evaluation",
                settings.EVALUATION_VERSION,
            )
            return self._tracer
        except ImportError:
            logger.info(
                "OpenTelemetry not available; Phoenix export disabled"
            )
            self._enabled = False
            return None
        except Exception as exc:
            logger.warning(
                "Failed to initialize Phoenix tracer: %s", exc
            )
            self._enabled = False
            return None

    async def export_evaluation(
        self,
        result: EvaluationResult,
    ) -> bool:
        """
        Export evaluation result to Phoenix as a span.

        Returns True if export succeeded, False otherwise.
        Export failure does not raise exceptions.
        """
        if not self._enabled:
            return False

        tracer = self._get_tracer()
        if tracer is None:
            return False

        try:
            with tracer.start_as_current_span(
                "evaluation.export_phoenix"
            ) as span:
                # Set evaluation attributes
                span.set_attribute(
                    "tars.evaluation.id",
                    result.evaluation_id,
                )
                span.set_attribute(
                    "tars.evaluation.version",
                    result.evaluator_version,
                )
                span.set_attribute(
                    "tars.evaluation.mission_id",
                    result.mission_id,
                )

                if result.overall_score is not None:
                    span.set_attribute(
                        "tars.evaluation.overall_score",
                        result.overall_score,
                    )

                span.set_attribute(
                    "tars.evaluation.false_positive",
                    result.false_positive,
                )
                span.set_attribute(
                    "tars.evaluation.false_negative",
                    result.false_negative,
                )

                if result.incident_id:
                    span.set_attribute(
                        "tars.evaluation.incident_id",
                        result.incident_id,
                    )

                if result.reasoning_id:
                    span.set_attribute(
                        "tars.evaluation.reasoning_id",
                        result.reasoning_id,
                    )

                if result.trace_id:
                    span.set_attribute(
                        "tars.evaluation.trace_id",
                        result.trace_id,
                    )

                # Set individual metric scores
                for metric in result.metrics:
                    if metric.score is not None:
                        attr_name = f"tars.evaluation.{metric.name.value}"
                        span.set_attribute(attr_name, metric.score)

            logger.info(
                "Exported evaluation '%s' to Phoenix",
                result.evaluation_id,
            )
            return True

        except Exception as exc:
            logger.warning(
                "Phoenix export failed for evaluation '%s': %s",
                result.evaluation_id,
                exc,
            )
            return False

    @property
    def is_enabled(self) -> bool:
        """Whether Phoenix export is enabled."""
        return self._enabled
