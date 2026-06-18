"""
Phase 9 Phoenix Exporter Tests
================================
Tests for the optional Phoenix evaluation exporter.

All tests run without a live Phoenix instance. The exporter is tested
in disabled mode and with mocked OpenTelemetry tracers.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from tars.phase9.models import (
    ClassificationLabel,
    EvaluationMetric,
    EvaluationResult,
    MetricName,
)
from tars.phase9.phoenix_exporter import PhoenixEvalExporter


# =============================================================================
# Helpers
# =============================================================================

def _make_eval_result(
    *,
    evaluation_id: str = "eval_phoenix_001",
    mission_id: str = "mission_001",
    incident_id: str | None = "inc_001",
    reasoning_id: str | None = "reason_001",
    trace_id: str | None = "trace_abc123",
    overall_score: float | None = 0.82,
) -> EvaluationResult:
    """Build an EvaluationResult for Phoenix export tests."""
    return EvaluationResult(
        evaluation_id=evaluation_id,
        mission_id=mission_id,
        incident_id=incident_id,
        reasoning_id=reasoning_id,
        trace_id=trace_id,
        overall_score=overall_score,
        false_positive=False,
        false_negative=False,
        evidence_level="operator_label",
        evaluator_version="v1.0-test",
        advisory_only=True,
        metrics=[
            EvaluationMetric(
                name=MetricName.ROOT_CAUSE_ACCURACY,
                score=0.9,
                label=ClassificationLabel.CORRECT,
                evidence=["operator_label"],
                explanation="Root cause matched.",
            ),
            EvaluationMetric(
                name=MetricName.RECOMMENDATION_ACCURACY,
                score=0.7,
                label=ClassificationLabel.PARTIALLY_CORRECT,
                evidence=["operator_label"],
                explanation="Recommendation partially matched.",
            ),
        ],
    )


# =============================================================================
# Disabled Mode
# =============================================================================

class TestDisabledExporter:
    """Test exporter when Phoenix is disabled."""

    @pytest.mark.asyncio
    async def test_export_returns_false_when_disabled(self):
        """Export should return False when disabled."""
        exporter = PhoenixEvalExporter()
        exporter._enabled = False

        result = await exporter.export_evaluation(_make_eval_result())
        assert result is False

    def test_is_enabled_property(self):
        """is_enabled should reflect internal state."""
        exporter = PhoenixEvalExporter()
        exporter._enabled = False
        assert exporter.is_enabled is False

        exporter._enabled = True
        assert exporter.is_enabled is True

    @pytest.mark.asyncio
    async def test_get_tracer_returns_none_when_disabled(self):
        """_get_tracer should return None when disabled."""
        exporter = PhoenixEvalExporter()
        exporter._enabled = False

        tracer = exporter._get_tracer()
        assert tracer is None


# =============================================================================
# Import Failure
# =============================================================================

class TestImportFailure:
    """Test exporter when OpenTelemetry is not installed."""

    @pytest.mark.asyncio
    async def test_export_handles_import_error(self):
        """Export should handle ImportError gracefully."""
        exporter = PhoenixEvalExporter()
        exporter._enabled = True
        exporter._tracer = None  # Force re-initialization

        with patch.dict("sys.modules", {"opentelemetry": None}):
            # _get_tracer should catch ImportError and disable
            tracer = exporter._get_tracer()
            # After import failure, should be disabled
            assert exporter.is_enabled is False


# =============================================================================
# Mocked Tracer
# =============================================================================

class TestMockedTracer:
    """Test exporter with a mocked OpenTelemetry tracer."""

    @pytest.mark.asyncio
    async def test_export_with_mocked_tracer(self):
        """Export should set span attributes with mocked tracer."""
        exporter = PhoenixEvalExporter()
        exporter._enabled = True

        # Create a mock tracer and span
        mock_span = MagicMock()
        mock_span.__enter__ = MagicMock(return_value=mock_span)
        mock_span.__exit__ = MagicMock(return_value=False)

        mock_tracer = MagicMock()
        mock_tracer.start_as_current_span.return_value = mock_span

        exporter._tracer = mock_tracer

        result_data = _make_eval_result()
        result = await exporter.export_evaluation(result_data)

        assert result is True
        mock_tracer.start_as_current_span.assert_called_once_with(
            "evaluation.export_phoenix"
        )
        # Verify span attributes were set
        assert mock_span.set_attribute.call_count > 0

    @pytest.mark.asyncio
    async def test_export_sets_evaluation_id_attribute(self):
        """Export should set tars.evaluation.id attribute."""
        exporter = PhoenixEvalExporter()
        exporter._enabled = True

        mock_span = MagicMock()
        mock_span.__enter__ = MagicMock(return_value=mock_span)
        mock_span.__exit__ = MagicMock(return_value=False)

        mock_tracer = MagicMock()
        mock_tracer.start_as_current_span.return_value = mock_span

        exporter._tracer = mock_tracer

        result_data = _make_eval_result(evaluation_id="eval_attr_test")
        await exporter.export_evaluation(result_data)

        # Check that evaluation ID was set
        calls = {
            call.args[0]: call.args[1]
            for call in mock_span.set_attribute.call_args_list
        }
        assert calls.get("tars.evaluation.id") == "eval_attr_test"

    @pytest.mark.asyncio
    async def test_export_sets_mission_id_attribute(self):
        """Export should set tars.evaluation.mission_id attribute."""
        exporter = PhoenixEvalExporter()
        exporter._enabled = True

        mock_span = MagicMock()
        mock_span.__enter__ = MagicMock(return_value=mock_span)
        mock_span.__exit__ = MagicMock(return_value=False)

        mock_tracer = MagicMock()
        mock_tracer.start_as_current_span.return_value = mock_span

        exporter._tracer = mock_tracer

        result_data = _make_eval_result(mission_id="mission_attr_test")
        await exporter.export_evaluation(result_data)

        calls = {
            call.args[0]: call.args[1]
            for call in mock_span.set_attribute.call_args_list
        }
        assert calls.get("tars.evaluation.mission_id") == "mission_attr_test"

    @pytest.mark.asyncio
    async def test_export_sets_overall_score_attribute(self):
        """Export should set tars.evaluation.overall_score attribute."""
        exporter = PhoenixEvalExporter()
        exporter._enabled = True

        mock_span = MagicMock()
        mock_span.__enter__ = MagicMock(return_value=mock_span)
        mock_span.__exit__ = MagicMock(return_value=False)

        mock_tracer = MagicMock()
        mock_tracer.start_as_current_span.return_value = mock_span

        exporter._tracer = mock_tracer

        result_data = _make_eval_result(overall_score=0.95)
        await exporter.export_evaluation(result_data)

        calls = {
            call.args[0]: call.args[1]
            for call in mock_span.set_attribute.call_args_list
        }
        assert calls.get("tars.evaluation.overall_score") == 0.95

    @pytest.mark.asyncio
    async def test_export_sets_metric_score_attributes(self):
        """Export should set per-metric score attributes."""
        exporter = PhoenixEvalExporter()
        exporter._enabled = True

        mock_span = MagicMock()
        mock_span.__enter__ = MagicMock(return_value=mock_span)
        mock_span.__exit__ = MagicMock(return_value=False)

        mock_tracer = MagicMock()
        mock_tracer.start_as_current_span.return_value = mock_span

        exporter._tracer = mock_tracer

        result_data = _make_eval_result()
        await exporter.export_evaluation(result_data)

        calls = {
            call.args[0]: call.args[1]
            for call in mock_span.set_attribute.call_args_list
        }
        assert "tars.evaluation.root_cause_accuracy" in calls
        assert "tars.evaluation.recommendation_accuracy" in calls

    @pytest.mark.asyncio
    async def test_export_sets_false_positive_attribute(self):
        """Export should set false_positive attribute."""
        exporter = PhoenixEvalExporter()
        exporter._enabled = True

        mock_span = MagicMock()
        mock_span.__enter__ = MagicMock(return_value=mock_span)
        mock_span.__exit__ = MagicMock(return_value=False)

        mock_tracer = MagicMock()
        mock_tracer.start_as_current_span.return_value = mock_span

        exporter._tracer = mock_tracer

        result_data = _make_eval_result()
        await exporter.export_evaluation(result_data)

        calls = {
            call.args[0]: call.args[1]
            for call in mock_span.set_attribute.call_args_list
        }
        assert calls.get("tars.evaluation.false_positive") is False

    @pytest.mark.asyncio
    async def test_export_without_optional_fields(self):
        """Export should handle None optional fields gracefully."""
        exporter = PhoenixEvalExporter()
        exporter._enabled = True

        mock_span = MagicMock()
        mock_span.__enter__ = MagicMock(return_value=mock_span)
        mock_span.__exit__ = MagicMock(return_value=False)

        mock_tracer = MagicMock()
        mock_tracer.start_as_current_span.return_value = mock_span

        exporter._tracer = mock_tracer

        result_data = _make_eval_result(
            incident_id=None,
            reasoning_id=None,
            trace_id=None,
            overall_score=None,
        )
        result = await exporter.export_evaluation(result_data)
        assert result is True

        # Should not set attributes for None fields
        attr_names = [
            call.args[0]
            for call in mock_span.set_attribute.call_args_list
        ]
        assert "tars.evaluation.incident_id" not in attr_names
        assert "tars.evaluation.reasoning_id" not in attr_names
        assert "tars.evaluation.trace_id" not in attr_names
        assert "tars.evaluation.overall_score" not in attr_names


# =============================================================================
# Exception Handling
# =============================================================================

class TestExceptionHandling:
    """Test that export exceptions are caught and don't propagate."""

    @pytest.mark.asyncio
    async def test_export_catches_tracer_exception(self):
        """Export should catch exceptions from tracer and return False."""
        exporter = PhoenixEvalExporter()
        exporter._enabled = True

        mock_tracer = MagicMock()
        mock_tracer.start_as_current_span.side_effect = RuntimeError(
            "Tracer error"
        )
        exporter._tracer = mock_tracer

        result = await exporter.export_evaluation(_make_eval_result())
        assert result is False

    @pytest.mark.asyncio
    async def test_export_catches_span_attribute_exception(self):
        """Export should catch exceptions from span.set_attribute."""
        exporter = PhoenixEvalExporter()
        exporter._enabled = True

        mock_span = MagicMock()
        mock_span.__enter__ = MagicMock(return_value=mock_span)
        mock_span.__exit__ = MagicMock(return_value=False)
        mock_span.set_attribute.side_effect = RuntimeError("Attribute error")

        mock_tracer = MagicMock()
        mock_tracer.start_as_current_span.return_value = mock_span

        exporter._tracer = mock_tracer

        result = await exporter.export_evaluation(_make_eval_result())
        assert result is False
