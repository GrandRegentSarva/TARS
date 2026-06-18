"""
Phase 9 Ground Truth Tests
============================
Tests for ground-truth resolution from multiple sources.

All tests run without live services.
"""

from __future__ import annotations

import pytest

from tars.phase9.ground_truth import GroundTruthLoader, GroundTruthResult
from tars.phase9.models import (
    EvidenceLevel,
    GroundTruthPayload,
    GroundTruthSource,
)

from .conftest import FakePhase7Client, FakeRepository


class TestGroundTruthResult:
    """Test GroundTruthResult construction."""

    def test_insufficient_result(self):
        """Insufficient result should have no evidence."""
        result = GroundTruthResult.insufficient()
        assert result.has_evidence is False
        assert result.label is None
        assert result.evidence_level is None


class TestGroundTruthLoader:
    """Test ground-truth resolution priority chain."""

    @pytest.mark.asyncio
    async def test_explicit_request_label_highest_priority(self):
        """Explicit request labels should take highest priority."""
        loader = GroundTruthLoader()
        payload = GroundTruthPayload(
            root_cause="gps_interference",
            preferred_mitigation="switch_to_visual_odometry",
            outcome="recovered",
        )
        result = await loader.resolve(
            mission_id="mission_001",
            request_ground_truth=payload,
        )
        assert result.has_evidence is True
        assert result.label is not None
        assert result.label.root_cause == "gps_interference"
        assert result.evidence_level == EvidenceLevel.OPERATOR_LABEL.value

    @pytest.mark.asyncio
    async def test_empty_payload_not_used(self):
        """Empty payload (no root_cause or outcome) should not be used."""
        loader = GroundTruthLoader()
        payload = GroundTruthPayload()
        result = await loader.resolve(
            mission_id="mission_001",
            request_ground_truth=payload,
        )
        assert result.has_evidence is False

    @pytest.mark.asyncio
    async def test_stored_labels_used_when_no_request(self):
        """Stored labels should be used when no request payload."""
        repo = FakeRepository()
        await repo.upsert_label(
            mission_id="mission_001",
            incident_id="inc_001",
            root_cause="gps_interference",
            preferred_mitigation="switch_to_visual_odometry",
            outcome="recovered",
            source="operator_label",
            labeled_by="test",
            labeled_at=None,
        )

        loader = GroundTruthLoader(repository=repo)
        result = await loader.resolve(
            mission_id="mission_001",
            incident_id="inc_001",
        )
        assert isinstance(result, GroundTruthResult)
        assert result.has_evidence is True
        assert result.label is not None
        assert result.label.root_cause == "gps_interference"
        assert result.label.preferred_mitigation == "switch_to_visual_odometry"
        assert result.label.outcome == "recovered"
        assert result.evidence_level == EvidenceLevel.OPERATOR_LABEL.value

    @pytest.mark.asyncio
    async def test_missing_labels_returns_insufficient(self):
        """Missing labels should return insufficient evidence."""
        repo = FakeRepository()
        loader = GroundTruthLoader(repository=repo)
        result = await loader.resolve(
            mission_id="mission_nonexistent",
        )
        assert result.has_evidence is False

    @pytest.mark.asyncio
    async def test_phase7_unavailable_does_not_fail(self):
        """Phase 7 unavailability should not fail evaluation."""
        phase7 = FakePhase7Client(unavailable=True)
        loader = GroundTruthLoader(phase7_client=phase7)
        result = await loader.resolve(
            mission_id="mission_001",
        )
        assert result.has_evidence is False

    @pytest.mark.asyncio
    async def test_no_sources_returns_insufficient(self):
        """No sources at all should return insufficient."""
        loader = GroundTruthLoader()
        result = await loader.resolve(
            mission_id="mission_001",
        )
        assert result.has_evidence is False
        assert result.label is None

    @pytest.mark.asyncio
    async def test_request_label_overrides_stored(self):
        """Request label should override stored labels."""
        repo = FakeRepository()
        await repo.upsert_label(
            mission_id="mission_001",
            incident_id=None,
            root_cause="old_cause",
            preferred_mitigation=None,
            outcome=None,
            source="operator_label",
            labeled_by="test",
            labeled_at=None,
        )

        loader = GroundTruthLoader(repository=repo)
        payload = GroundTruthPayload(
            root_cause="new_cause",
            outcome="recovered",
        )
        result = await loader.resolve(
            mission_id="mission_001",
            request_ground_truth=payload,
        )
        assert result.has_evidence is True
        assert result.label.root_cause == "new_cause"
