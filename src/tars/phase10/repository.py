"""
Phase 10 Learning Repository
==============================
Async PostgreSQL operations for learning runs, candidate knowledge,
and candidate evidence.

Provides:
- Create and update learning runs.
- Upsert candidate knowledge by dedupe key.
- Store candidate evidence.
- List candidates by filters with pagination.
- Fetch one candidate and paginated evidence.
- Retire candidates.
- Link candidates to learning runs.

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
    CandidateKnowledge,
    CandidateResponse,
    CandidateStatus,
    EvidenceResponse,
    LearningEvidence,
    LearningRunResponse,
    LearningRunStatus,
    RunCandidateAction,
)

logger = logging.getLogger("phase10.repository")


class LearningRepository:
    """
    Async repository for Phase 10 learning persistence.

    Uses raw SQL via SQLAlchemy text() for clarity and control.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # -----------------------------------------------------------------------
    # Learning Runs
    # -----------------------------------------------------------------------

    async def create_run(
        self,
        run_id: str,
        filters: dict,
        learning_version: str,
        dry_run: bool = False,
    ) -> LearningRunResponse:
        """Create a new learning run record."""
        now = datetime.now(timezone.utc)

        await self._session.execute(
            text("""
                INSERT INTO learning_runs (
                    run_id, status, filters_json, learning_version,
                    dry_run, started_at
                ) VALUES (
                    :run_id, :status, :filters_json, :learning_version,
                    :dry_run, :started_at
                )
            """),
            {
                "run_id": run_id,
                "status": LearningRunStatus.RUNNING.value,
                "filters_json": json.dumps(filters),
                "learning_version": learning_version,
                "dry_run": dry_run,
                "started_at": now,
            },
        )
        await self._session.commit()

        return LearningRunResponse(
            run_id=run_id,
            status=LearningRunStatus.RUNNING,
            started_at=now,
            filters=filters,
            learning_version=learning_version,
            dry_run=dry_run,
        )

    async def complete_run(
        self,
        run_id: str,
        evaluated_cases_read: int,
        evidence_items_used: int,
        candidates_proposed: int,
        candidates_updated: int,
        candidates_suppressed: int,
        candidate_ids: list[str],
        warnings: list[str],
    ) -> None:
        """Mark a learning run as complete with summary stats."""
        now = datetime.now(timezone.utc)

        await self._session.execute(
            text("""
                UPDATE learning_runs
                SET status = :status,
                    evaluated_cases_read = :evaluated_cases_read,
                    evidence_items_used = :evidence_items_used,
                    candidates_proposed = :candidates_proposed,
                    candidates_updated = :candidates_updated,
                    candidates_suppressed = :candidates_suppressed,
                    warnings_json = :warnings_json,
                    completed_at = :completed_at
                WHERE run_id = :run_id
            """),
            {
                "run_id": run_id,
                "status": LearningRunStatus.COMPLETE.value,
                "evaluated_cases_read": evaluated_cases_read,
                "evidence_items_used": evidence_items_used,
                "candidates_proposed": candidates_proposed,
                "candidates_updated": candidates_updated,
                "candidates_suppressed": candidates_suppressed,
                "warnings_json": json.dumps(warnings),
                "completed_at": now,
            },
        )
        await self._session.commit()

    async def fail_run(
        self,
        run_id: str,
        error_code: str,
        error_message: str,
        warnings: Optional[list[str]] = None,
    ) -> None:
        """Mark a learning run as failed."""
        now = datetime.now(timezone.utc)

        await self._session.execute(
            text("""
                UPDATE learning_runs
                SET status = :status,
                    error_code = :error_code,
                    error_message = :error_message,
                    warnings_json = :warnings_json,
                    completed_at = :completed_at
                WHERE run_id = :run_id
            """),
            {
                "run_id": run_id,
                "status": LearningRunStatus.FAILED.value,
                "error_code": error_code,
                "error_message": error_message[:2000] if error_message else "",
                "warnings_json": json.dumps(warnings or []),
                "completed_at": now,
            },
        )
        await self._session.commit()

    async def get_run(self, run_id: str) -> Optional[LearningRunResponse]:
        """Fetch a learning run by ID."""
        result = await self._session.execute(
            text("""
                SELECT run_id, status, filters_json, learning_version,
                       evaluated_cases_read, evidence_items_used,
                       candidates_proposed, candidates_updated,
                       candidates_suppressed, warnings_json,
                       dry_run, started_at, completed_at,
                       error_code, error_message
                FROM learning_runs
                WHERE run_id = :run_id
            """),
            {"run_id": run_id},
        )
        row = result.mappings().first()
        if row is None:
            return None

        filters = row["filters_json"]
        if isinstance(filters, str):
            filters = json.loads(filters)

        warnings = row["warnings_json"]
        if isinstance(warnings, str):
            warnings = json.loads(warnings)

        # Load candidate IDs for this run
        cand_result = await self._session.execute(
            text("""
                SELECT candidate_id FROM learning_run_candidates
                WHERE run_id = :run_id
                  AND action IN ('proposed', 'updated')
            """),
            {"run_id": run_id},
        )
        candidate_ids = [r["candidate_id"] for r in cand_result.mappings().all()]

        return LearningRunResponse(
            run_id=row["run_id"],
            status=LearningRunStatus(row["status"]),
            started_at=row["started_at"],
            completed_at=row["completed_at"],
            filters=filters,
            evaluated_cases_read=row["evaluated_cases_read"],
            evidence_items_used=row["evidence_items_used"],
            candidates_proposed=row["candidates_proposed"],
            candidates_updated=row["candidates_updated"],
            candidates_suppressed=row["candidates_suppressed"],
            candidate_ids=candidate_ids,
            warnings=warnings,
            error_code=row["error_code"],
            error_message=row["error_message"],
            learning_version=row["learning_version"],
            dry_run=row["dry_run"],
        )

    # -----------------------------------------------------------------------
    # Candidate Knowledge
    # -----------------------------------------------------------------------

    async def find_active_candidate_by_dedupe_key(
        self,
        dedupe_key: str,
        learning_version: str,
    ) -> Optional[CandidateResponse]:
        """Find an active (proposed) candidate by dedupe key."""
        result = await self._session.execute(
            text("""
                SELECT candidate_id, candidate_type, status, statement,
                       incident_family, root_cause, mitigation, outcome_family,
                       support_count, contradiction_count, distinct_mission_count,
                       success_rate, mean_overall_score, confidence,
                       learning_version, dedupe_key, supersedes_candidate_id,
                       advisory_only, created_at, updated_at
                FROM candidate_knowledge
                WHERE dedupe_key = :dedupe_key
                  AND learning_version = :learning_version
                  AND status = 'proposed'
            """),
            {
                "dedupe_key": dedupe_key,
                "learning_version": learning_version,
            },
        )
        row = result.mappings().first()
        if row is None:
            return None

        return self._row_to_candidate_response(row)

    async def upsert_candidate(
        self,
        candidate: CandidateKnowledge,
        evidence_items: list[LearningEvidence],
    ) -> tuple[str, bool]:
        """
        Upsert a candidate by dedupe key.

        If an active candidate with the same dedupe key exists, supersede it.
        Returns (candidate_id, is_new).
        """
        now = datetime.now(timezone.utc)

        # Check for existing active candidate
        existing = await self.find_active_candidate_by_dedupe_key(
            candidate.dedupe_key,
            candidate.learning_version,
        )

        if existing is not None:
            # Supersede the old candidate
            await self._session.execute(
                text("""
                    UPDATE candidate_knowledge
                    SET status = 'superseded',
                        updated_at = :updated_at
                    WHERE candidate_id = :candidate_id
                """),
                {
                    "candidate_id": existing.candidate_id,
                    "updated_at": now,
                },
            )
            candidate.supersedes_candidate_id = existing.candidate_id

        # Insert new candidate
        await self._session.execute(
            text("""
                INSERT INTO candidate_knowledge (
                    candidate_id, candidate_type, status, statement,
                    incident_family, root_cause, mitigation, outcome_family,
                    support_count, contradiction_count, distinct_mission_count,
                    success_rate, mean_overall_score, confidence,
                    learning_version, dedupe_key, supersedes_candidate_id,
                    advisory_only, created_at, updated_at
                ) VALUES (
                    :candidate_id, :candidate_type, :status, :statement,
                    :incident_family, :root_cause, :mitigation, :outcome_family,
                    :support_count, :contradiction_count, :distinct_mission_count,
                    :success_rate, :mean_overall_score, :confidence,
                    :learning_version, :dedupe_key, :supersedes_candidate_id,
                    :advisory_only, :created_at, :updated_at
                )
            """),
            {
                "candidate_id": candidate.candidate_id,
                "candidate_type": candidate.candidate_type.value,
                "status": candidate.status.value,
                "statement": candidate.statement,
                "incident_family": candidate.incident_family,
                "root_cause": candidate.root_cause,
                "mitigation": candidate.mitigation,
                "outcome_family": candidate.outcome_family,
                "support_count": candidate.support_count,
                "contradiction_count": candidate.contradiction_count,
                "distinct_mission_count": candidate.distinct_mission_count,
                "success_rate": candidate.success_rate,
                "mean_overall_score": candidate.mean_overall_score,
                "confidence": candidate.confidence,
                "learning_version": candidate.learning_version,
                "dedupe_key": candidate.dedupe_key,
                "supersedes_candidate_id": candidate.supersedes_candidate_id,
                "advisory_only": True,
                "created_at": now,
                "updated_at": now,
            },
        )

        # Insert evidence items
        for ev in evidence_items:
            await self._session.execute(
                text("""
                    INSERT INTO candidate_evidence (
                        evidence_id, candidate_id, mission_id, incident_id,
                        reasoning_id, evaluation_id, trace_id,
                        root_cause, mitigation, outcome, overall_score,
                        metric_labels_json, evidence_levels_json, created_at
                    ) VALUES (
                        :evidence_id, :candidate_id, :mission_id, :incident_id,
                        :reasoning_id, :evaluation_id, :trace_id,
                        :root_cause, :mitigation, :outcome, :overall_score,
                        :metric_labels_json, :evidence_levels_json, :created_at
                    )
                """),
                {
                    "evidence_id": ev.evidence_id,
                    "candidate_id": candidate.candidate_id,
                    "mission_id": ev.mission_id,
                    "incident_id": ev.incident_id,
                    "reasoning_id": ev.reasoning_id,
                    "evaluation_id": ev.evaluation_id,
                    "trace_id": ev.trace_id,
                    "root_cause": ev.root_cause,
                    "mitigation": ev.mitigation,
                    "outcome": ev.outcome,
                    "overall_score": ev.overall_score,
                    "metric_labels_json": json.dumps(ev.metric_labels),
                    "evidence_levels_json": json.dumps(ev.evidence_levels),
                    "created_at": now,
                },
            )

        await self._session.commit()

        is_new = existing is None
        logger.info(
            "%s candidate '%s' (dedupe_key='%s')",
            "Created" if is_new else "Updated",
            candidate.candidate_id,
            candidate.dedupe_key,
        )
        return candidate.candidate_id, is_new

    async def link_candidate_to_run(
        self,
        run_id: str,
        candidate_id: str,
        action: RunCandidateAction,
    ) -> None:
        """Link a candidate to a learning run with an action."""
        now = datetime.now(timezone.utc)

        await self._session.execute(
            text("""
                INSERT INTO learning_run_candidates (
                    run_id, candidate_id, action, created_at
                ) VALUES (
                    :run_id, :candidate_id, :action, :created_at
                )
                ON CONFLICT (run_id, candidate_id) DO UPDATE
                SET action = :action
            """),
            {
                "run_id": run_id,
                "candidate_id": candidate_id,
                "action": action.value,
                "created_at": now,
            },
        )
        await self._session.commit()

    async def get_candidate(
        self,
        candidate_id: str,
    ) -> Optional[CandidateResponse]:
        """Get a single candidate by ID."""
        result = await self._session.execute(
            text("""
                SELECT candidate_id, candidate_type, status, statement,
                       incident_family, root_cause, mitigation, outcome_family,
                       support_count, contradiction_count, distinct_mission_count,
                       success_rate, mean_overall_score, confidence,
                       learning_version, dedupe_key, supersedes_candidate_id,
                       advisory_only, created_at, updated_at
                FROM candidate_knowledge
                WHERE candidate_id = :candidate_id
            """),
            {"candidate_id": candidate_id},
        )
        row = result.mappings().first()
        if row is None:
            return None

        # Load evidence IDs
        ev_result = await self._session.execute(
            text("""
                SELECT evidence_id, evaluation_id, trace_id
                FROM candidate_evidence
                WHERE candidate_id = :candidate_id
            """),
            {"candidate_id": candidate_id},
        )
        ev_rows = ev_result.mappings().all()

        evidence_ids = [r["evidence_id"] for r in ev_rows]
        eval_ids = [
            r["evaluation_id"] for r in ev_rows if r["evaluation_id"]
        ]
        trace_ids = [
            r["trace_id"] for r in ev_rows if r["trace_id"]
        ]

        resp = self._row_to_candidate_response(row)
        resp.evidence_ids = evidence_ids
        resp.source_evaluation_ids = eval_ids
        resp.source_trace_ids = trace_ids
        return resp

    async def list_candidates(
        self,
        candidate_type: Optional[str] = None,
        status: Optional[str] = None,
        incident_family: Optional[str] = None,
        root_cause: Optional[str] = None,
        min_confidence: Optional[float] = None,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[CandidateResponse], int]:
        """
        List candidates with optional filters and pagination.

        Returns (candidates, total_count).
        """
        conditions = []
        params: dict[str, Any] = {}

        if candidate_type:
            conditions.append("candidate_type = :candidate_type")
            params["candidate_type"] = candidate_type
        if status:
            conditions.append("status = :status")
            params["status"] = status
        if incident_family:
            conditions.append("incident_family = :incident_family")
            params["incident_family"] = incident_family
        if root_cause:
            conditions.append("root_cause = :root_cause")
            params["root_cause"] = root_cause
        if min_confidence is not None:
            conditions.append("confidence >= :min_confidence")
            params["min_confidence"] = min_confidence

        where_clause = ""
        if conditions:
            where_clause = "WHERE " + " AND ".join(conditions)

        # Count
        count_result = await self._session.execute(
            text(f"SELECT COUNT(*) FROM candidate_knowledge {where_clause}"),
            params,
        )
        total = count_result.scalar() or 0

        # Fetch page
        offset = (page - 1) * page_size
        params["limit"] = page_size
        params["offset"] = offset

        result = await self._session.execute(
            text(f"""
                SELECT candidate_id, candidate_type, status, statement,
                       incident_family, root_cause, mitigation, outcome_family,
                       support_count, contradiction_count, distinct_mission_count,
                       success_rate, mean_overall_score, confidence,
                       learning_version, dedupe_key, supersedes_candidate_id,
                       advisory_only, created_at, updated_at
                FROM candidate_knowledge
                {where_clause}
                ORDER BY confidence DESC, created_at DESC
                LIMIT :limit OFFSET :offset
            """),
            params,
        )
        rows = result.mappings().all()

        candidates = [self._row_to_candidate_response(row) for row in rows]
        return candidates, total

    async def get_evidence(
        self,
        candidate_id: str,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[EvidenceResponse], int]:
        """
        Get paginated evidence for a candidate.

        Returns (evidence_items, total_count).
        """
        # Count
        count_result = await self._session.execute(
            text("""
                SELECT COUNT(*) FROM candidate_evidence
                WHERE candidate_id = :candidate_id
            """),
            {"candidate_id": candidate_id},
        )
        total = count_result.scalar() or 0

        # Fetch page
        offset = (page - 1) * page_size
        result = await self._session.execute(
            text("""
                SELECT evidence_id, candidate_id, mission_id, incident_id,
                       reasoning_id, evaluation_id, trace_id,
                       root_cause, mitigation, outcome, overall_score,
                       metric_labels_json, evidence_levels_json, created_at
                FROM candidate_evidence
                WHERE candidate_id = :candidate_id
                ORDER BY created_at DESC
                LIMIT :limit OFFSET :offset
            """),
            {
                "candidate_id": candidate_id,
                "limit": page_size,
                "offset": offset,
            },
        )
        rows = result.mappings().all()

        evidence = []
        for row in rows:
            metric_labels = row["metric_labels_json"]
            if isinstance(metric_labels, str):
                metric_labels = json.loads(metric_labels)

            evidence_levels = row["evidence_levels_json"]
            if isinstance(evidence_levels, str):
                evidence_levels = json.loads(evidence_levels)

            evidence.append(
                EvidenceResponse(
                    evidence_id=row["evidence_id"],
                    candidate_id=row["candidate_id"],
                    mission_id=row["mission_id"],
                    incident_id=row["incident_id"],
                    reasoning_id=row["reasoning_id"],
                    evaluation_id=row["evaluation_id"],
                    trace_id=row["trace_id"],
                    root_cause=row["root_cause"],
                    mitigation=row["mitigation"],
                    outcome=row["outcome"],
                    overall_score=row["overall_score"],
                    metric_labels=metric_labels,
                    evidence_levels=evidence_levels,
                    created_at=row["created_at"],
                )
            )

        return evidence, total

    async def retire_candidate(
        self,
        candidate_id: str,
        reason: str,
    ) -> bool:
        """
        Retire a candidate with a reason.

        Returns True if the candidate was found and retired.
        """
        now = datetime.now(timezone.utc)

        result = await self._session.execute(
            text("""
                UPDATE candidate_knowledge
                SET status = 'retired',
                    retire_reason = :reason,
                    updated_at = :updated_at
                WHERE candidate_id = :candidate_id
                  AND status = 'proposed'
            """),
            {
                "candidate_id": candidate_id,
                "reason": reason[:500],
                "updated_at": now,
            },
        )
        await self._session.commit()

        affected = result.rowcount
        if affected > 0:
            logger.info("Retired candidate '%s': %s", candidate_id, reason)
            return True
        return False

    # -----------------------------------------------------------------------
    # Internal Helpers
    # -----------------------------------------------------------------------

    def _row_to_candidate_response(self, row: Any) -> CandidateResponse:
        """Convert a database row to a CandidateResponse."""
        from .models import CandidateType, CandidateStatus

        return CandidateResponse(
            candidate_id=row["candidate_id"],
            candidate_type=CandidateType(row["candidate_type"]),
            status=CandidateStatus(row["status"]),
            statement=row["statement"],
            incident_family=row["incident_family"],
            root_cause=row["root_cause"],
            mitigation=row["mitigation"],
            outcome_family=row["outcome_family"],
            support_count=row["support_count"],
            contradiction_count=row["contradiction_count"],
            distinct_mission_count=row["distinct_mission_count"],
            success_rate=row["success_rate"],
            mean_overall_score=row["mean_overall_score"],
            confidence=row["confidence"],
            learning_version=row["learning_version"],
            dedupe_key=row["dedupe_key"],
            supersedes_candidate_id=row["supersedes_candidate_id"],
            advisory_only=row["advisory_only"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
