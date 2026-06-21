"""
Phase 10 Repository Tests
============================
Tests for run persistence, candidate upsert, evidence pagination,
and retire flow using the in-memory fake repository.
"""

from __future__ import annotations

import pytest

from tars.phase10.models import (
    CandidateKnowledge,
    CandidateStatus,
    CandidateType,
    LearningEvidence,
    LearningRunStatus,
    RunCandidateAction,
)

from .conftest import FakeRepository, make_evidence


class TestRunPersistence:
    """Test learning run persistence."""

    @pytest.mark.asyncio
    async def test_create_run(self, fake_repository):
        """Creating a run should store it."""
        result = await fake_repository.create_run(
            run_id="run_001",
            filters={"incident_family": "navigation_instability"},
            learning_version="phase10.v1",
        )
        assert result.run_id == "run_001"
        assert result.status == LearningRunStatus.RUNNING

    @pytest.mark.asyncio
    async def test_complete_run(self, fake_repository):
        """Completing a run should update its status."""
        await fake_repository.create_run(
            run_id="run_002",
            filters={},
            learning_version="phase10.v1",
        )
        await fake_repository.complete_run(
            run_id="run_002",
            evaluated_cases_read=10,
            evidence_items_used=8,
            candidates_proposed=2,
            candidates_updated=0,
            candidates_suppressed=3,
            candidate_ids=["cand_001", "cand_002"],
            warnings=[],
        )
        run = await fake_repository.get_run("run_002")
        assert run is not None
        assert run.status == LearningRunStatus.COMPLETE

    @pytest.mark.asyncio
    async def test_fail_run(self, fake_repository):
        """Failing a run should update its status."""
        await fake_repository.create_run(
            run_id="run_003",
            filters={},
            learning_version="phase10.v1",
        )
        await fake_repository.fail_run(
            run_id="run_003",
            error_code="TEST_ERROR",
            error_message="Test failure",
        )
        run = await fake_repository.get_run("run_003")
        assert run is not None
        assert run.status == LearningRunStatus.FAILED

    @pytest.mark.asyncio
    async def test_get_nonexistent_run(self, fake_repository):
        """Getting a nonexistent run should return None."""
        result = await fake_repository.get_run("nonexistent")
        assert result is None


class TestCandidateUpsert:
    """Test candidate knowledge upsert."""

    @pytest.mark.asyncio
    async def test_create_new_candidate(self, fake_repository):
        """Creating a new candidate should return is_new=True."""
        candidate = CandidateKnowledge(
            candidate_id="cand_new_001",
            candidate_type=CandidateType.MITIGATION_EFFECTIVENESS,
            statement="Test candidate.",
            dedupe_key="test:dedupe:key",
            learning_version="phase10.v1",
            confidence=0.75,
        )
        evidence = [make_evidence()]
        cand_id, is_new = await fake_repository.upsert_candidate(
            candidate, evidence
        )
        assert cand_id == "cand_new_001"
        assert is_new is True

    @pytest.mark.asyncio
    async def test_upsert_supersedes_existing(self, fake_repository):
        """Upserting with same dedupe key should supersede old candidate."""
        # Create first candidate
        c1 = CandidateKnowledge(
            candidate_id="cand_v1",
            candidate_type=CandidateType.MITIGATION_EFFECTIVENESS,
            statement="Version 1.",
            dedupe_key="same:key",
            learning_version="phase10.v1",
            confidence=0.70,
        )
        await fake_repository.upsert_candidate(c1, [make_evidence()])

        # Create second with same dedupe key
        c2 = CandidateKnowledge(
            candidate_id="cand_v2",
            candidate_type=CandidateType.MITIGATION_EFFECTIVENESS,
            statement="Version 2.",
            dedupe_key="same:key",
            learning_version="phase10.v1",
            confidence=0.80,
        )
        cand_id, is_new = await fake_repository.upsert_candidate(
            c2, [make_evidence()]
        )
        assert is_new is False

        # Old candidate should be superseded
        old = await fake_repository.get_candidate("cand_v1")
        assert old is not None
        assert old.status == CandidateStatus.SUPERSEDED

    @pytest.mark.asyncio
    async def test_get_candidate(self, fake_repository):
        """Getting a candidate should return its details."""
        candidate = CandidateKnowledge(
            candidate_id="cand_get_001",
            candidate_type=CandidateType.ROOT_CAUSE_PATTERN,
            statement="Test root cause pattern.",
            dedupe_key="get:test",
            learning_version="phase10.v1",
            confidence=0.65,
            support_count=5,
        )
        await fake_repository.upsert_candidate(candidate, [])
        result = await fake_repository.get_candidate("cand_get_001")
        assert result is not None
        assert result.candidate_id == "cand_get_001"
        assert result.advisory_only is True

    @pytest.mark.asyncio
    async def test_get_nonexistent_candidate(self, fake_repository):
        """Getting a nonexistent candidate should return None."""
        result = await fake_repository.get_candidate("nonexistent")
        assert result is None


class TestCandidateListing:
    """Test candidate listing with filters."""

    @pytest.mark.asyncio
    async def test_list_all_candidates(self, fake_repository):
        """Listing should return all candidates."""
        for i in range(3):
            c = CandidateKnowledge(
                candidate_id=f"cand_list_{i:03d}",
                candidate_type=CandidateType.MITIGATION_EFFECTIVENESS,
                statement=f"Candidate {i}.",
                dedupe_key=f"list:key:{i}",
                learning_version="phase10.v1",
                confidence=0.70 + i * 0.05,
            )
            await fake_repository.upsert_candidate(c, [])

        candidates, total = await fake_repository.list_candidates()
        assert total == 3
        assert len(candidates) == 3

    @pytest.mark.asyncio
    async def test_list_by_type(self, fake_repository):
        """Listing by type should filter correctly."""
        c1 = CandidateKnowledge(
            candidate_id="cand_type_1",
            candidate_type=CandidateType.MITIGATION_EFFECTIVENESS,
            statement="Mitigation.",
            dedupe_key="type:1",
            learning_version="phase10.v1",
        )
        c2 = CandidateKnowledge(
            candidate_id="cand_type_2",
            candidate_type=CandidateType.ROOT_CAUSE_PATTERN,
            statement="Root cause.",
            dedupe_key="type:2",
            learning_version="phase10.v1",
        )
        await fake_repository.upsert_candidate(c1, [])
        await fake_repository.upsert_candidate(c2, [])

        candidates, total = await fake_repository.list_candidates(
            candidate_type="root_cause_pattern"
        )
        assert total == 1
        assert candidates[0].candidate_type == CandidateType.ROOT_CAUSE_PATTERN


class TestEvidencePagination:
    """Test evidence pagination."""

    @pytest.mark.asyncio
    async def test_paginated_evidence(self, fake_repository):
        """Evidence should be paginated."""
        evidence = [
            make_evidence(evidence_id=f"ev_{i:03d}")
            for i in range(10)
        ]
        candidate = CandidateKnowledge(
            candidate_id="cand_ev_001",
            candidate_type=CandidateType.MITIGATION_EFFECTIVENESS,
            statement="Test.",
            dedupe_key="ev:test",
            learning_version="phase10.v1",
        )
        await fake_repository.upsert_candidate(candidate, evidence)

        page1, total = await fake_repository.get_evidence(
            "cand_ev_001", page=1, page_size=5
        )
        assert total == 10
        assert len(page1) == 5

        page2, _ = await fake_repository.get_evidence(
            "cand_ev_001", page=2, page_size=5
        )
        assert len(page2) == 5


class TestRetireFlow:
    """Test candidate retirement."""

    @pytest.mark.asyncio
    async def test_retire_proposed_candidate(self, fake_repository):
        """Retiring a proposed candidate should succeed."""
        candidate = CandidateKnowledge(
            candidate_id="cand_retire_001",
            candidate_type=CandidateType.MITIGATION_EFFECTIVENESS,
            statement="To be retired.",
            dedupe_key="retire:test",
            learning_version="phase10.v1",
        )
        await fake_repository.upsert_candidate(candidate, [])

        result = await fake_repository.retire_candidate(
            "cand_retire_001", "No longer relevant."
        )
        assert result is True

        retired = await fake_repository.get_candidate("cand_retire_001")
        assert retired is not None
        assert retired.status == CandidateStatus.RETIRED

    @pytest.mark.asyncio
    async def test_retire_nonexistent_candidate(self, fake_repository):
        """Retiring a nonexistent candidate should return False."""
        result = await fake_repository.retire_candidate(
            "nonexistent", "reason"
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_retire_already_retired(self, fake_repository):
        """Retiring an already retired candidate should return False."""
        candidate = CandidateKnowledge(
            candidate_id="cand_double_retire",
            candidate_type=CandidateType.MITIGATION_EFFECTIVENESS,
            statement="Double retire test.",
            dedupe_key="double:retire",
            learning_version="phase10.v1",
        )
        await fake_repository.upsert_candidate(candidate, [])
        await fake_repository.retire_candidate(
            "cand_double_retire", "First retire."
        )
        result = await fake_repository.retire_candidate(
            "cand_double_retire", "Second retire."
        )
        assert result is False
