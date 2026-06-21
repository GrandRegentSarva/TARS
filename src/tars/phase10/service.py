"""
Phase 10 Learning Service
===========================
Orchestrates learning runs from evidence loading through candidate persistence.

Responsibilities:
1. Create learning run record.
2. Load bounded evidence from Phase 9, Phase 7, and Phoenix.
3. Mine patterns from evidence.
4. Score candidates.
5. Persist or dry-run candidates.
6. Update run status and warnings.

The service never invokes an LLM, mutates upstream records, promotes
validated knowledge, or calls flight-control APIs.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from .config import settings
from .evidence_loader import EvidenceLoader
from .models import (
    CandidateKnowledge,
    CandidateStatus,
    CandidateType,
    LearningEvidence,
    LearningRunRequest,
    LearningRunResponse,
    LearningRunStatus,
    RunCandidateAction,
)
from .pattern_miner import PatternGroup, PatternMiner
from .repository import LearningRepository
from .scorer import CandidateScorer
from .statement_templates import generate_statement

logger = logging.getLogger("phase10.service")


class LearningService:
    """
    Service layer for Phase 10 learning.

    Coordinates evidence loading, pattern mining, scoring,
    and candidate persistence.
    """

    def __init__(
        self,
        repository: LearningRepository,
        evidence_loader: EvidenceLoader,
        pattern_miner: Optional[PatternMiner] = None,
        scorer: Optional[CandidateScorer] = None,
    ) -> None:
        self._repository = repository
        self._evidence_loader = evidence_loader
        self._pattern_miner = pattern_miner or PatternMiner()
        self._scorer = scorer or CandidateScorer()

    async def run_learning(
        self,
        request: LearningRunRequest,
    ) -> LearningRunResponse:
        """
        Execute a bounded learning run.

        Steps:
        1. Create learning run record.
        2. Load bounded evidence.
        3. Mine patterns.
        4. Score candidates.
        5. Persist or dry-run candidates.
        6. Update run status.

        Args:
            request: Learning run request with filters.

        Returns:
            LearningRunResponse with run summary.
        """
        run_id = f"learnrun_{uuid.uuid4().hex[:16]}"
        warnings: list[str] = []

        # Build filters dict for persistence
        filters = self._build_filters(request)

        # 1. Create run record (skip for dry runs to avoid DB requirement)
        if not request.dry_run:
            try:
                await self._repository.create_run(
                    run_id=run_id,
                    filters=filters,
                    learning_version=settings.LEARNING_VERSION,
                    dry_run=request.dry_run,
                )
            except Exception as exc:
                logger.error("Failed to create learning run: %s", exc)
                return self._failed_response(
                    run_id=run_id,
                    error_code="RUN_CREATE_FAILED",
                    error_message=str(exc),
                    filters=filters,
                    dry_run=request.dry_run,
                )

        try:
            # 2. Load bounded evidence
            since_str = request.since.isoformat() if request.since else None
            until_str = request.until.isoformat() if request.until else None

            evidence_items, load_warnings = await self._evidence_loader.load_evidence(
                mission_ids=request.mission_ids or None,
                incident_family=request.incident_family,
                root_cause=request.root_cause,
                since=since_str,
                until=until_str,
                limit=settings.LEARNING_BATCH_LIMIT,
            )
            warnings.extend(load_warnings)

            if not evidence_items:
                warnings.append("No evidence items found. Learning run produced no candidates.")
                if not request.dry_run:
                    await self._repository.complete_run(
                        run_id=run_id,
                        evaluated_cases_read=0,
                        evidence_items_used=0,
                        candidates_proposed=0,
                        candidates_updated=0,
                        candidates_suppressed=0,
                        candidate_ids=[],
                        warnings=warnings,
                    )
                return LearningRunResponse(
                    run_id=run_id,
                    status=LearningRunStatus.COMPLETE,
                    started_at=datetime.now(timezone.utc),
                    completed_at=datetime.now(timezone.utc),
                    filters=filters,
                    evaluated_cases_read=0,
                    evidence_items_used=0,
                    candidates_proposed=0,
                    candidates_updated=0,
                    candidates_suppressed=0,
                    candidate_ids=[],
                    warnings=warnings,
                    learning_version=settings.LEARNING_VERSION,
                    dry_run=request.dry_run,
                )

            # 3. Mine patterns (respect per-request threshold overrides)
            miner = self._pattern_miner
            if request.min_evaluated_cases != settings.LEARNING_MIN_EVALUATED_CASES:
                miner = PatternMiner(
                    min_evaluated_cases=request.min_evaluated_cases,
                )
            patterns, suppressions = miner.mine_patterns(
                evidence_items,
                candidate_types=request.candidate_types,
            )

            # Add suppression warnings
            for s in suppressions:
                warnings.append(
                    f"Suppressed {s.candidate_type.value} pattern "
                    f"'{s.group_key}': {s.reason}"
                )

            # 4. Score and build candidates
            candidates_proposed = 0
            candidates_updated = 0
            candidates_suppressed = len(suppressions)
            candidate_ids: list[str] = []

            for pattern in patterns:
                # Score the pattern
                confidence = self._scorer.score(pattern)

                # Check minimum confidence
                if confidence < settings.LEARNING_MIN_CONFIDENCE:
                    candidates_suppressed += 1
                    warnings.append(
                        f"Suppressed {pattern.candidate_type.value} pattern "
                        f"'{pattern.group_key}': confidence {confidence:.3f} "
                        f"< {settings.LEARNING_MIN_CONFIDENCE}"
                    )
                    continue

                # Build candidate
                candidate = self._build_candidate(pattern, confidence)

                # Get evidence items for this pattern
                pattern_evidence = pattern.all_items

                if request.dry_run:
                    # Dry run: don't persist
                    candidates_proposed += 1
                    candidate_ids.append(candidate.candidate_id)
                else:
                    # Persist candidate
                    try:
                        cand_id, is_new = await self._repository.upsert_candidate(
                            candidate=candidate,
                            evidence_items=pattern_evidence,
                        )

                        action = (
                            RunCandidateAction.PROPOSED
                            if is_new
                            else RunCandidateAction.UPDATED
                        )

                        await self._repository.link_candidate_to_run(
                            run_id=run_id,
                            candidate_id=cand_id,
                            action=action,
                        )

                        if is_new:
                            candidates_proposed += 1
                        else:
                            candidates_updated += 1

                        candidate_ids.append(cand_id)

                    except Exception as exc:
                        logger.error(
                            "Failed to persist candidate '%s': %s",
                            candidate.candidate_id,
                            exc,
                        )
                        warnings.append(
                            f"Failed to persist candidate: {str(exc)[:200]}"
                        )

            # 5. Complete run
            if not request.dry_run:
                await self._repository.complete_run(
                    run_id=run_id,
                    evaluated_cases_read=len(evidence_items),
                    evidence_items_used=sum(
                        p.total_count for p in patterns
                    ),
                    candidates_proposed=candidates_proposed,
                    candidates_updated=candidates_updated,
                    candidates_suppressed=candidates_suppressed,
                    candidate_ids=candidate_ids,
                    warnings=warnings,
                )

            return LearningRunResponse(
                run_id=run_id,
                status=LearningRunStatus.COMPLETE,
                started_at=datetime.now(timezone.utc),
                completed_at=datetime.now(timezone.utc),
                filters=filters,
                evaluated_cases_read=len(evidence_items),
                evidence_items_used=sum(
                    p.total_count for p in patterns
                ),
                candidates_proposed=candidates_proposed,
                candidates_updated=candidates_updated,
                candidates_suppressed=candidates_suppressed,
                candidate_ids=candidate_ids,
                warnings=warnings,
                learning_version=settings.LEARNING_VERSION,
                dry_run=request.dry_run,
            )

        except Exception as exc:
            logger.error("Learning run '%s' failed: %s", run_id, exc)

            if not request.dry_run:
                try:
                    await self._repository.fail_run(
                        run_id=run_id,
                        error_code="RUN_FAILED",
                        error_message=str(exc),
                        warnings=warnings,
                    )
                except Exception as fail_exc:
                    logger.error(
                        "Failed to record run failure: %s", fail_exc
                    )

            return self._failed_response(
                run_id=run_id,
                error_code="RUN_FAILED",
                error_message=str(exc),
                filters=filters,
                warnings=warnings,
                dry_run=request.dry_run,
            )

    async def get_run(self, run_id: str) -> Optional[LearningRunResponse]:
        """Get a learning run by ID."""
        return await self._repository.get_run(run_id)

    # -----------------------------------------------------------------------
    # Internal Helpers
    # -----------------------------------------------------------------------

    def _build_filters(self, request: LearningRunRequest) -> dict:
        """Build a filters dict from the request."""
        filters: dict[str, Any] = {}
        if request.mission_ids:
            filters["mission_ids"] = request.mission_ids
        if request.incident_family:
            filters["incident_family"] = request.incident_family
        if request.root_cause:
            filters["root_cause"] = request.root_cause
        if request.candidate_types:
            filters["candidate_types"] = [
                ct.value for ct in request.candidate_types
            ]
        if request.since:
            filters["since"] = request.since.isoformat()
        if request.until:
            filters["until"] = request.until.isoformat()
        return filters

    def _build_candidate(
        self,
        pattern: PatternGroup,
        confidence: float,
    ) -> CandidateKnowledge:
        """Build a CandidateKnowledge from a scored pattern."""
        candidate_id = f"cand_{uuid.uuid4().hex[:16]}"

        # Generate deterministic statement
        statement = generate_statement(pattern)

        # Build dedupe key
        dedupe_key = self._build_dedupe_key(pattern)

        # Collect IDs from evidence
        evidence_ids = [e.evidence_id for e in pattern.all_items]
        eval_ids = [
            e.evaluation_id for e in pattern.all_items
            if e.evaluation_id
        ]
        trace_ids = [
            e.trace_id for e in pattern.all_items
            if e.trace_id
        ]

        return CandidateKnowledge(
            candidate_id=candidate_id,
            candidate_type=pattern.candidate_type,
            status=CandidateStatus.PROPOSED,
            statement=statement,
            incident_family=pattern.incident_family,
            root_cause=pattern.root_cause,
            mitigation=pattern.mitigation,
            outcome_family=pattern.outcome_family,
            support_count=pattern.support_count,
            contradiction_count=pattern.contradiction_count,
            distinct_mission_count=pattern.distinct_mission_count,
            success_rate=round(pattern.success_rate, 4),
            mean_overall_score=(
                round(pattern.mean_overall_score, 4)
                if pattern.mean_overall_score is not None
                else None
            ),
            confidence=confidence,
            evidence_ids=evidence_ids,
            source_evaluation_ids=eval_ids,
            source_trace_ids=trace_ids,
            learning_version=settings.LEARNING_VERSION,
            dedupe_key=dedupe_key,
            advisory_only=True,
        )

    def _build_dedupe_key(self, pattern: PatternGroup) -> str:
        """Build a deterministic deduplication key for a pattern."""
        parts = [pattern.candidate_type.value]

        if pattern.incident_family:
            parts.append(pattern.incident_family)
        if pattern.root_cause:
            parts.append(pattern.root_cause)
        if pattern.mitigation:
            parts.append(pattern.mitigation)
        if pattern.metric_name:
            parts.append(pattern.metric_name)
        if pattern.outcome_family:
            parts.append(pattern.outcome_family)

        return ":".join(parts)

    def _failed_response(
        self,
        run_id: str,
        error_code: str,
        error_message: str,
        filters: Optional[dict] = None,
        warnings: Optional[list[str]] = None,
        dry_run: bool = False,
    ) -> LearningRunResponse:
        """Build a failed run response."""
        now = datetime.now(timezone.utc)
        return LearningRunResponse(
            run_id=run_id,
            status=LearningRunStatus.FAILED,
            started_at=now,
            completed_at=now,
            filters=filters or {},
            error_code=error_code,
            error_message=error_message[:2000],
            warnings=warnings or [],
            learning_version=settings.LEARNING_VERSION,
            dry_run=dry_run,
        )
