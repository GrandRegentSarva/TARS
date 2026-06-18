"""
Phase 9 Repository Tests
=========================
Tests for the in-memory FakeRepository and repository contract.

These tests verify the repository interface contract without requiring
a live PostgreSQL instance. Integration tests with a real database
are gated behind a ``--run-postgres`` marker.
"""

from __future__ import annotations

import pytest

from tars.phase9.models import (
    ClassificationLabel,
    EvaluationMetric,
    EvaluationResult,
    GroundTruthSource,
    MetricName,
)

from .conftest import FakeRepository


# =============================================================================
# Helpers
# =============================================================================

def _make_result(
    *,
    evaluation_id: str = "eval_test_001",
    mission_id: str = "mission_001",
    incident_id: str | None = "inc_001",
    reasoning_id: str | None = "reason_001",
    overall_score: float | None = 0.75,
    evaluator_version: str = "v1.0-test",
) -> EvaluationResult:
    """Build a minimal EvaluationResult for repository tests."""
    return EvaluationResult(
        evaluation_id=evaluation_id,
        mission_id=mission_id,
        incident_id=incident_id,
        reasoning_id=reasoning_id,
        overall_score=overall_score,
        false_positive=False,
        false_negative=False,
        evidence_level="operator_label",
        evaluator_version=evaluator_version,
        advisory_only=True,
        metrics=[
            EvaluationMetric(
                name=MetricName.ROOT_CAUSE_ACCURACY,
                score=0.8,
                label=ClassificationLabel.CORRECT,
                evidence=["operator_label"],
                explanation="Root cause matched ground truth.",
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
# Save and Retrieve
# =============================================================================

class TestSaveAndRetrieve:
    """Test saving and retrieving evaluations."""

    @pytest.mark.asyncio
    async def test_save_and_get_by_id(self):
        """Saved evaluation should be retrievable by ID."""
        repo = FakeRepository()
        result = _make_result()

        eval_id = await repo.save_evaluation(result)
        assert eval_id == "eval_test_001"

        retrieved = await repo.get_evaluation("eval_test_001")
        assert retrieved is not None
        assert retrieved.evaluation_id == "eval_test_001"

    @pytest.mark.asyncio
    async def test_get_nonexistent_returns_none(self):
        """Getting a nonexistent evaluation should return None."""
        repo = FakeRepository()
        retrieved = await repo.get_evaluation("nonexistent")
        assert retrieved is None

    @pytest.mark.asyncio
    async def test_save_multiple_and_get_by_mission(self):
        """Multiple evaluations for same mission should all be returned."""
        repo = FakeRepository()

        r1 = _make_result(
            evaluation_id="eval_001",
            incident_id="inc_001",
            reasoning_id="reason_001",
        )
        r2 = _make_result(
            evaluation_id="eval_002",
            incident_id="inc_002",
            reasoning_id="reason_002",
        )

        await repo.save_evaluation(r1)
        await repo.save_evaluation(r2)

        results = await repo.get_evaluations_by_mission("mission_001")
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_get_by_reasoning(self):
        """Evaluations should be retrievable by reasoning ID."""
        repo = FakeRepository()

        r1 = _make_result(
            evaluation_id="eval_001",
            reasoning_id="reason_target",
        )
        r2 = _make_result(
            evaluation_id="eval_002",
            reasoning_id="reason_other",
            incident_id="inc_002",
        )

        await repo.save_evaluation(r1)
        await repo.save_evaluation(r2)

        results = await repo.get_evaluations_by_reasoning("reason_target")
        assert len(results) == 1
        assert results[0].evaluation_id == "eval_001"


# =============================================================================
# Idempotency
# =============================================================================

class TestIdempotency:
    """Test duplicate detection and overwrite."""

    @pytest.mark.asyncio
    async def test_find_existing_evaluation(self):
        """find_existing_evaluation should return saved result."""
        repo = FakeRepository()
        result = _make_result()
        await repo.save_evaluation(result)

        existing = await repo.find_existing_evaluation(
            mission_id="mission_001",
            incident_id="inc_001",
            reasoning_id="reason_001",
            evaluator_version="v1.0-test",
        )
        assert existing is not None

    @pytest.mark.asyncio
    async def test_find_existing_returns_none_when_not_found(self):
        """find_existing_evaluation should return None for new targets."""
        repo = FakeRepository()

        existing = await repo.find_existing_evaluation(
            mission_id="mission_new",
            incident_id="inc_new",
            reasoning_id="reason_new",
            evaluator_version="v1.0-test",
        )
        assert existing is None

    @pytest.mark.asyncio
    async def test_overwrite_replaces_evaluation(self):
        """overwrite_evaluation should replace existing result."""
        repo = FakeRepository()

        r1 = _make_result(evaluation_id="eval_001", overall_score=0.5)
        await repo.save_evaluation(r1)

        r2 = _make_result(evaluation_id="eval_002", overall_score=0.9)
        await repo.overwrite_evaluation(r2)

        # The overwrite should have replaced the entry
        retrieved = await repo.get_evaluation("eval_002")
        assert retrieved is not None


# =============================================================================
# Labels
# =============================================================================

class TestLabels:
    """Test ground-truth label operations."""

    @pytest.mark.asyncio
    async def test_upsert_label(self):
        """upsert_label should create a new label."""
        repo = FakeRepository()

        label = await repo.upsert_label(
            mission_id="mission_001",
            incident_id="inc_001",
            root_cause="gps_interference",
            preferred_mitigation="switch_to_visual_odometry",
            outcome="recovered",
            source="operator_label",
            labeled_by="test_operator",
            labeled_at=None,
        )

        assert label.label_id is not None
        assert label.mission_id == "mission_001"
        assert label.root_cause == "gps_interference"

    @pytest.mark.asyncio
    async def test_get_labels_for_target(self):
        """get_labels_for_target should return matching labels."""
        repo = FakeRepository()

        await repo.upsert_label(
            mission_id="mission_001",
            incident_id="inc_001",
            root_cause="gps_interference",
            preferred_mitigation=None,
            outcome="recovered",
            source="operator_label",
            labeled_by="test",
            labeled_at=None,
        )
        await repo.upsert_label(
            mission_id="mission_001",
            incident_id="inc_002",
            root_cause="battery_failure",
            preferred_mitigation=None,
            outcome="failed",
            source="operator_label",
            labeled_by="test",
            labeled_at=None,
        )

        labels = await repo.get_labels_for_target(
            mission_id="mission_001",
            incident_id="inc_001",
        )
        assert len(labels) == 1
        assert labels[0].root_cause == "gps_interference"

    @pytest.mark.asyncio
    async def test_get_labels_empty(self):
        """get_labels_for_target should return empty list when none exist."""
        repo = FakeRepository()

        labels = await repo.get_labels_for_target(
            mission_id="mission_nonexistent",
        )
        assert labels == []


# =============================================================================
# Similar Evaluations
# =============================================================================

class TestSimilarEvaluations:
    """Test similar evaluation lookup."""

    @pytest.mark.asyncio
    async def test_get_similar_evaluations_returns_empty(self):
        """FakeRepository returns empty list for similar evaluations."""
        repo = FakeRepository()

        similar = await repo.get_similar_evaluations(
            incident_type="navigation_instability",
            severity="high",
            root_cause_family="gps",
        )
        assert similar == []

    @pytest.mark.asyncio
    async def test_get_similar_evaluations_with_limit(self):
        """Similar evaluations should respect limit parameter."""
        repo = FakeRepository()

        similar = await repo.get_similar_evaluations(
            incident_type="navigation_instability",
            severity="high",
            root_cause_family="gps",
            limit=5,
        )
        assert isinstance(similar, list)
        assert len(similar) <= 5
