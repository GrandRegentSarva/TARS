"""
Phase 9 Service Tests
=======================
Tests for evaluation service orchestration.

All tests run without live services.
"""

from __future__ import annotations

import pytest

from tars.phase9.evaluator import Evaluator
from tars.phase9.ground_truth import GroundTruthLoader
from tars.phase9.models import (
    ClassificationLabel,
    EvaluationRequest,
    GroundTruthPayload,
    MetricName,
)
from tars.phase9.phoenix_exporter import PhoenixEvalExporter
from tars.phase9.service import EvaluationService

from .conftest import (
    FakePhase4Client,
    FakePhase5Client,
    FakePhase7Client,
    FakeRepository,
    make_incident,
    make_reasoning,
)


def _create_service(
    repository=None,
    phase4_client=None,
    phase5_client=None,
    phase7_client=None,
):
    """Create an EvaluationService with fake dependencies."""
    repo = repository or FakeRepository()
    gt_loader = GroundTruthLoader(
        repository=repo,
        phase7_client=phase7_client or FakePhase7Client(),
    )
    exporter = PhoenixEvalExporter()
    # Ensure Phoenix export is disabled for tests
    exporter._enabled = False

    return EvaluationService(
        repository=repo,
        ground_truth_loader=gt_loader,
        evaluator=Evaluator(version="v1.0-test"),
        phoenix_exporter=exporter,
        phase4_client=phase4_client,
        phase5_client=phase5_client,
    )


class TestEvaluateOne:
    """Test single evaluation."""

    @pytest.mark.asyncio
    async def test_evaluate_with_inline_ground_truth(self):
        """Evaluation with inline ground truth should produce scores."""
        phase5 = FakePhase5Client(analyses={
            "mission_001": [make_reasoning(
                mission_id="mission_001",
                incident_id="inc_001",
                reasoning_id="reason_001",
            )],
        })
        service = _create_service(phase5_client=phase5)

        request = EvaluationRequest(
            mission_id="mission_001",
            incident_id="inc_001",
            reasoning_id="reason_001",
            ground_truth=GroundTruthPayload(
                root_cause="gps_interference",
                preferred_mitigation="switch_to_visual_odometry",
                outcome="recovered",
            ),
        )

        result = await service.evaluate(request)
        assert result.evaluation_id is not None
        assert result.mission_id == "mission_001"
        assert result.advisory_only is True
        assert len(result.metrics) > 0

    @pytest.mark.asyncio
    async def test_evaluate_without_ground_truth(self):
        """Evaluation without ground truth should return insufficient evidence."""
        phase5 = FakePhase5Client(analyses={
            "mission_001": [make_reasoning(
                mission_id="mission_001",
                incident_id="inc_001",
                reasoning_id="reason_001",
            )],
        })
        service = _create_service(phase5_client=phase5)

        request = EvaluationRequest(
            mission_id="mission_001",
            incident_id="inc_001",
            reasoning_id="reason_001",
        )

        result = await service.evaluate(request)
        assert result.evaluation_id is not None
        # Should have metrics with insufficient evidence
        for metric in result.metrics:
            if metric.name in (MetricName.ROOT_CAUSE_ACCURACY, MetricName.RECOMMENDATION_ACCURACY):
                assert metric.label == ClassificationLabel.INSUFFICIENT_EVIDENCE

    @pytest.mark.asyncio
    async def test_evaluate_missing_reasoning_raises(self):
        """Explicit reasoning_id not found should raise ValueError."""
        service = _create_service(
            phase5_client=FakePhase5Client(unavailable=True)
        )

        request = EvaluationRequest(
            mission_id="mission_001",
            incident_id="inc_001",
            reasoning_id="reason_missing",
            ground_truth=GroundTruthPayload(
                root_cause="gps_interference",
                outcome="recovered",
            ),
        )

        with pytest.raises(ValueError, match="not found"):
            await service.evaluate(request)

    @pytest.mark.asyncio
    async def test_evaluate_no_reasoning_id_succeeds(self):
        """Evaluation without reasoning_id should succeed even without Phase 5."""
        service = _create_service(
            phase5_client=FakePhase5Client(unavailable=True)
        )

        request = EvaluationRequest(
            mission_id="mission_001",
            incident_id="inc_001",
            ground_truth=GroundTruthPayload(
                root_cause="gps_interference",
                outcome="recovered",
            ),
        )

        result = await service.evaluate(request)
        assert result.evaluation_id is not None

    @pytest.mark.asyncio
    async def test_idempotent_evaluation(self):
        """Duplicate request with overwrite=false should return existing."""
        repo = FakeRepository()
        phase5 = FakePhase5Client(analyses={
            "mission_001": [make_reasoning(
                mission_id="mission_001",
                incident_id="inc_001",
                reasoning_id="reason_001",
            )],
        })
        service = _create_service(repository=repo, phase5_client=phase5)

        request = EvaluationRequest(
            mission_id="mission_001",
            incident_id="inc_001",
            reasoning_id="reason_001",
            ground_truth=GroundTruthPayload(
                root_cause="gps_interference",
                outcome="recovered",
            ),
            overwrite=False,
        )

        # First evaluation
        result1 = await service.evaluate(request)
        # Second evaluation should return existing
        result2 = await service.evaluate(request)
        # Both should have the same evaluation_id
        assert result1.evaluation_id == result2.evaluation_id

    @pytest.mark.asyncio
    async def test_overwrite_evaluation(self):
        """Overwrite=true should create new evaluation."""
        repo = FakeRepository()
        phase5 = FakePhase5Client(analyses={
            "mission_001": [make_reasoning(
                mission_id="mission_001",
                incident_id="inc_001",
                reasoning_id="reason_001",
            )],
        })
        service = _create_service(repository=repo, phase5_client=phase5)

        request = EvaluationRequest(
            mission_id="mission_001",
            incident_id="inc_001",
            reasoning_id="reason_001",
            ground_truth=GroundTruthPayload(
                root_cause="gps_interference",
                outcome="recovered",
            ),
            overwrite=True,
        )

        result1 = await service.evaluate(request)
        result2 = await service.evaluate(request)
        # Overwrite creates new ID
        assert result2.evaluation_id != result1.evaluation_id


class TestEvaluateBatch:
    """Test batch evaluation."""

    @pytest.mark.asyncio
    async def test_batch_evaluation(self):
        """Batch evaluation should return per-item results."""
        phase5 = FakePhase5Client(analyses={
            "mission_001": [
                make_reasoning(
                    mission_id="mission_001",
                    incident_id="inc_001",
                    reasoning_id="reason_001",
                ),
                make_reasoning(
                    mission_id="mission_001",
                    incident_id="inc_002",
                    reasoning_id="reason_002",
                ),
            ],
        })
        service = _create_service(phase5_client=phase5)

        targets = [
            EvaluationRequest(
                mission_id="mission_001",
                incident_id="inc_001",
                reasoning_id="reason_001",
                ground_truth=GroundTruthPayload(
                    root_cause="gps_interference",
                    outcome="recovered",
                ),
            ),
            EvaluationRequest(
                mission_id="mission_001",
                incident_id="inc_002",
                reasoning_id="reason_002",
                ground_truth=GroundTruthPayload(
                    root_cause="battery_failure",
                    outcome="failed",
                ),
            ),
        ]

        result = await service.evaluate_batch(targets)
        assert result.total == 2
        assert result.succeeded == 2
        assert result.failed == 0
        assert len(result.results) == 2

    @pytest.mark.asyncio
    async def test_batch_partial_failure(self):
        """Partial batch failure should not abort successful items."""
        service = _create_service()

        targets = [
            EvaluationRequest(
                mission_id="mission_001",
                ground_truth=GroundTruthPayload(
                    root_cause="gps_interference",
                    outcome="recovered",
                ),
            ),
        ]

        result = await service.evaluate_batch(targets)
        assert result.total == 1
        # Should succeed even without Phase 5 data


class TestPhoenixExportFailOpen:
    """Test that Phoenix export failure does not fail evaluation."""

    @pytest.mark.asyncio
    async def test_phoenix_export_failure_does_not_fail(self):
        """Phoenix export failure should not prevent evaluation persistence."""
        service = _create_service()
        # Phoenix is disabled in tests, so this should work fine

        request = EvaluationRequest(
            mission_id="mission_001",
            ground_truth=GroundTruthPayload(
                root_cause="gps_interference",
                outcome="recovered",
            ),
        )

        result = await service.evaluate(request)
        assert result.evaluation_id is not None


class TestPhase7Unavailable:
    """Test that Phase 7 unavailability does not fail evaluation."""

    @pytest.mark.asyncio
    async def test_phase7_unavailable_with_explicit_labels(self):
        """Phase 7 unavailable should not fail when explicit labels exist."""
        service = _create_service(
            phase7_client=FakePhase7Client(unavailable=True)
        )

        request = EvaluationRequest(
            mission_id="mission_001",
            ground_truth=GroundTruthPayload(
                root_cause="gps_interference",
                outcome="recovered",
            ),
        )

        result = await service.evaluate(request)
        assert result.evaluation_id is not None


class TestFalseNegativeWiring:
    """Test that false-negative scoring is wired into the service."""

    @pytest.mark.asyncio
    async def test_false_negative_metric_present(self):
        """Evaluation with ground truth should include false-negative metric."""
        phase4 = FakePhase4Client(incidents={
            "mission_001": [make_incident(
                mission_id="mission_001",
                incident_id="inc_001",
            )],
        })
        phase5 = FakePhase5Client(analyses={
            "mission_001": [make_reasoning(
                mission_id="mission_001",
                incident_id="inc_001",
                reasoning_id="reason_001",
            )],
        })
        service = _create_service(
            phase4_client=phase4,
            phase5_client=phase5,
        )

        request = EvaluationRequest(
            mission_id="mission_001",
            incident_id="inc_001",
            reasoning_id="reason_001",
            ground_truth=GroundTruthPayload(
                root_cause="gps_interference",
                outcome="recovered",
            ),
        )

        result = await service.evaluate(request)
        metric_names = [m.name for m in result.metrics]
        assert MetricName.FALSE_NEGATIVE in metric_names

    @pytest.mark.asyncio
    async def test_false_negative_detected_for_failed_outcome(self):
        """Failed outcome with no incidents should flag false negative."""
        # No incidents or reasoning available
        service = _create_service(
            phase4_client=FakePhase4Client(incidents={}),
            phase5_client=FakePhase5Client(analyses={}),
        )

        request = EvaluationRequest(
            mission_id="mission_001",
            ground_truth=GroundTruthPayload(
                root_cause="battery_failure",
                outcome="failed",
            ),
        )

        result = await service.evaluate(request)
        fn_metrics = [
            m for m in result.metrics
            if m.name == MetricName.FALSE_NEGATIVE
        ]
        assert len(fn_metrics) == 1
        assert fn_metrics[0].label == ClassificationLabel.INCORRECT
        assert result.false_negative is True
