"""
Phase 7 Memory Service
=======================
Orchestrates pull-based mission synchronization, observation recording,
and bounded history queries.

Responsibilities:
- Sync a completed mission from upstream APIs into Neo4j
- Record explicit applied mitigations and outcomes
- Query incident neighborhoods and similar history
- Manage sync status and error reporting
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from .config import settings
from .mapper import (
    build_mission_projection,
    generate_deterministic_id,
    normalize_text,
)
from .models import (
    AppliedMitigationInfo,
    ApplyMitigationResponse,
    IncidentMemoryResponse,
    MitigationInfo,
    OutcomeInfo,
    OutcomeScope,
    OutcomeStatus,
    RecordOutcomeResponse,
    RootCauseInfo,
    SimilarHistoryResponse,
    SimilarIncidentMatch,
    SyncCounts,
    SyncResponse,
    SyncStatus,
    SyncStatusResponse,
)
from .phase2_client import Phase2Client, Phase2ClientError, Phase2NotFoundError
from .phase4_client import Phase4Client, Phase4ClientError, Phase4UnavailableError
from .phase5_client import Phase5Client, Phase5ClientError, Phase5UnavailableError
from . import repository

logger = logging.getLogger("phase7.service")


class MemoryService:
    """
    Operational Memory service orchestrating sync, observations, and queries.
    """

    def __init__(
        self,
        phase2_client: Optional[Phase2Client] = None,
        phase4_client: Optional[Phase4Client] = None,
        phase5_client: Optional[Phase5Client] = None,
    ) -> None:
        self._phase2 = phase2_client or Phase2Client()
        self._phase4 = phase4_client or Phase4Client()
        self._phase5 = phase5_client or Phase5Client()

    # =========================================================================
    # Mission Synchronization
    # =========================================================================

    async def sync_mission(
        self,
        mission_id: str,
        include_reasoning: bool = True,
        require_reasoning: bool = False,
    ) -> SyncResponse:
        """
        Synchronize a completed mission into the operational memory graph.

        1. Fetch mission detail from Phase 2
        2. Fetch incidents from Phase 4
        3. Optionally fetch reasoning from Phase 5
        4. Map into graph records
        5. Write one idempotent graph transaction
        6. Record sync status

        Args:
            mission_id: Phase 2 mission identifier.
            include_reasoning: Whether to fetch Phase 5 analyses.
            require_reasoning: If true, fail when Phase 5 is unavailable.

        Returns:
            SyncResponse with status and counts.
        """
        started_at = datetime.now(timezone.utc)

        # Record sync as processing
        try:
            await repository.upsert_sync_status(
                mission_id=mission_id,
                status=SyncStatus.PROCESSING.value,
                started_at=started_at,
            )
        except Exception as exc:
            logger.warning("Failed to record sync start: %s", exc)

        try:
            # 1. Fetch mission from Phase 2
            try:
                mission_data = await self._phase2.get_mission(mission_id)
            except Phase2NotFoundError:
                return await self._fail_sync(
                    mission_id, started_at,
                    error_code="mission_not_found",
                    error_message=f"Mission '{mission_id}' not found in Phase 2",
                )
            except Phase2ClientError as exc:
                return await self._fail_sync(
                    mission_id, started_at,
                    error_code="phase2_unavailable",
                    error_message=str(exc),
                )

            # 2. Fetch incidents from Phase 4
            try:
                incidents_data = await self._phase4.get_incidents(mission_id)
            except Phase4UnavailableError as exc:
                return await self._fail_sync(
                    mission_id, started_at,
                    error_code="phase4_unavailable",
                    error_message=str(exc),
                )
            except Phase4ClientError as exc:
                return await self._fail_sync(
                    mission_id, started_at,
                    error_code="phase4_error",
                    error_message=str(exc),
                )

            # 3. Optionally fetch reasoning from Phase 5
            reasoning_list: Optional[list[dict[str, Any]]] = None
            analyses_skipped = 0

            if include_reasoning:
                try:
                    reasoning_list = await self._phase5.get_analyses(mission_id)
                except Phase5UnavailableError as exc:
                    if require_reasoning:
                        return await self._fail_sync(
                            mission_id, started_at,
                            error_code="phase5_unavailable",
                            error_message=str(exc),
                        )
                    logger.warning(
                        "Phase 5 unavailable for mission '%s'; "
                        "skipping reasoning: %s",
                        mission_id, exc,
                    )
                    reasoning_list = None
                    analyses_skipped = len(incidents_data)
                except Phase5ClientError as exc:
                    if require_reasoning:
                        return await self._fail_sync(
                            mission_id, started_at,
                            error_code="phase5_error",
                            error_message=str(exc),
                        )
                    logger.warning(
                        "Phase 5 error for mission '%s'; "
                        "skipping reasoning: %s",
                        mission_id, exc,
                    )
                    reasoning_list = None
                    analyses_skipped = len(incidents_data)

            # 4. Build projection
            try:
                projection = build_mission_projection(
                    mission_data=mission_data,
                    incidents_data=incidents_data,
                    reasoning_list=reasoning_list,
                )
            except ValueError as exc:
                return await self._fail_sync(
                    mission_id, started_at,
                    error_code="mapping_error",
                    error_message=str(exc),
                )

            # 5. Write graph transaction
            counts = await repository.project_mission(projection)
            counts.analyses_skipped = analyses_skipped

            # 6. Record sync as complete
            completed_at = datetime.now(timezone.utc)
            try:
                await repository.upsert_sync_status(
                    mission_id=mission_id,
                    status=SyncStatus.COMPLETE.value,
                    started_at=started_at,
                    completed_at=completed_at,
                    counts=counts,
                )
            except Exception as exc:
                logger.warning("Failed to record sync completion: %s", exc)

            return SyncResponse(
                mission_id=mission_id,
                status=SyncStatus.COMPLETE,
                counts=counts,
                started_at=started_at,
                completed_at=completed_at,
            )

        except Exception as exc:
            logger.error(
                "Unexpected error syncing mission '%s': %s",
                mission_id, exc,
            )
            return await self._fail_sync(
                mission_id, started_at,
                error_code="internal_error",
                error_message=f"Unexpected sync error: {type(exc).__name__}",
            )

    async def _fail_sync(
        self,
        mission_id: str,
        started_at: datetime,
        error_code: str,
        error_message: str,
    ) -> SyncResponse:
        """Record a failed sync and return the response."""
        completed_at = datetime.now(timezone.utc)
        try:
            await repository.upsert_sync_status(
                mission_id=mission_id,
                status=SyncStatus.FAILED.value,
                started_at=started_at,
                completed_at=completed_at,
                error_code=error_code,
                error_message=error_message,
            )
        except Exception as exc:
            logger.warning("Failed to record sync failure: %s", exc)

        return SyncResponse(
            mission_id=mission_id,
            status=SyncStatus.FAILED,
            started_at=started_at,
            completed_at=completed_at,
            error_code=error_code,
            error_message=error_message,
        )

    # =========================================================================
    # Sync Status
    # =========================================================================

    async def get_sync_status(self, mission_id: str) -> Optional[SyncStatusResponse]:
        """Get the sync status for a mission."""
        data = await repository.get_sync_status(mission_id)
        if data is None:
            return None

        counts = SyncCounts(
            missions=data.get("counts_missions", 0) or 0,
            incidents=data.get("counts_incidents", 0) or 0,
            root_causes=data.get("counts_root_causes", 0) or 0,
            mitigations=data.get("counts_mitigations", 0) or 0,
            outcomes=data.get("counts_outcomes", 0) or 0,
            relationships=data.get("counts_relationships", 0) or 0,
            analyses_skipped=data.get("counts_analyses_skipped", 0) or 0,
        )

        return SyncStatusResponse(
            mission_id=data["mission_id"],
            status=SyncStatus(data["status"]),
            started_at=data.get("started_at"),
            completed_at=data.get("completed_at"),
            counts=counts,
            error_code=data.get("error_code"),
            error_message=data.get("error_message"),
        )

    # =========================================================================
    # Explicit Observations
    # =========================================================================

    async def apply_mitigation(
        self,
        incident_id: str,
        idempotency_key: str,
        description: str,
        applied_at: datetime,
        recorded_by: str,
        notes: Optional[str] = None,
    ) -> ApplyMitigationResponse:
        """
        Record an explicitly applied mitigation for an incident.

        Args:
            incident_id: Target incident identifier.
            idempotency_key: Caller-supplied idempotency key.
            description: Human-readable mitigation description.
            applied_at: When the mitigation was applied.
            recorded_by: Actor or system that recorded this.
            notes: Optional bounded notes.

        Returns:
            ApplyMitigationResponse with application details.

        Raises:
            ValueError: If the incident does not exist in the graph.
        """
        normalized = normalize_text(description)
        mitigation_id = generate_deterministic_id("mit", normalized)

        result = await repository.record_applied_mitigation(
            incident_id=incident_id,
            application_id=idempotency_key,
            description=description,
            normalized_description=normalized,
            mitigation_id=mitigation_id,
            applied_at=applied_at,
            recorded_by=recorded_by,
            notes=notes,
        )

        return ApplyMitigationResponse(
            application_id=result["application_id"],
            incident_id=result["incident_id"],
            mitigation_id=result["mitigation_id"],
            description=result["description"],
            applied_at=applied_at if result["created"] else _parse_dt(result["applied_at"]),
            recorded_by=result["recorded_by"],
            notes=result.get("notes"),
            created=result["created"],
        )

    async def record_outcome(
        self,
        incident_id: str,
        idempotency_key: str,
        status: OutcomeStatus,
        description: str,
        observed_at: datetime,
        recorded_by: str,
        mitigation_application_id: Optional[str] = None,
    ) -> RecordOutcomeResponse:
        """
        Record an explicit outcome observation for an incident.

        Args:
            incident_id: Target incident identifier.
            idempotency_key: Caller-supplied idempotency key.
            status: Controlled outcome status.
            description: Bounded factual description.
            observed_at: When the outcome was observed.
            recorded_by: Actor or system that recorded this.
            mitigation_application_id: Optional mitigation application reference.

        Returns:
            RecordOutcomeResponse with outcome details.

        Raises:
            ValueError: If the incident does not exist in the graph.
        """
        result = await repository.record_outcome(
            incident_id=incident_id,
            outcome_id=idempotency_key,
            scope=OutcomeScope.INCIDENT.value,
            status=status.value,
            description=description,
            observed_at=observed_at,
            recorded_by=recorded_by,
            mitigation_application_id=mitigation_application_id,
        )

        return RecordOutcomeResponse(
            outcome_id=result["outcome_id"],
            incident_id=result["incident_id"],
            scope=OutcomeScope.INCIDENT,
            status=status if result["created"] else OutcomeStatus(result["status"]),
            description=result["description"],
            observed_at=observed_at if result["created"] else _parse_dt(result["observed_at"]),
            recorded_by=result["recorded_by"],
            mitigation_application_id=result.get("mitigation_application_id"),
            created=result["created"],
        )

    # =========================================================================
    # Queries
    # =========================================================================

    async def get_incident_memory(
        self,
        incident_id: str,
    ) -> Optional[IncidentMemoryResponse]:
        """
        Get the bounded graph neighborhood for one incident.

        Returns:
            IncidentMemoryResponse or None if incident not found.
        """
        data = await repository.get_incident_neighborhood(incident_id)
        if data is None:
            return None

        inc = data["incident"]

        root_causes = [
            RootCauseInfo(
                root_cause_id=rc["root_cause_id"],
                classification=rc["classification"],
                confidence=rc.get("confidence", 0.0),
                reasoning_id=rc.get("reasoning_id"),
                model=rc.get("model"),
                prompt_version=rc.get("prompt_version"),
                rationale=rc.get("rationale"),
                uncertainties=rc.get("uncertainties", []),
                source_phase=rc.get("source_phase", "phase5"),
            )
            for rc in data.get("root_causes", [])
        ]

        recommended = [
            MitigationInfo(
                mitigation_id=m["mitigation_id"],
                description=m["description"],
                advisory_only=m.get("advisory_only", True),
                source=m.get("source", "phase5_recommendation"),
            )
            for m in data.get("recommended_mitigations", [])
        ]

        applied = [
            AppliedMitigationInfo(
                application_id=m["application_id"],
                mitigation_id=m["mitigation_id"],
                description=m["description"],
                applied_at=_parse_dt(m["applied_at"]),
                recorded_by=m["recorded_by"],
                notes=m.get("notes"),
            )
            for m in data.get("applied_mitigations", [])
        ]

        outcomes = [
            OutcomeInfo(
                outcome_id=o["outcome_id"],
                scope=OutcomeScope(o.get("scope", "incident")),
                status=OutcomeStatus(o.get("status", "unknown")),
                description=o["description"],
                observed_at=_parse_dt(o["observed_at"]),
                recorded_by=o.get("recorded_by", "unknown"),
                source=o.get("source", "explicit_observation"),
            )
            for o in data.get("outcomes", [])
        ]

        return IncidentMemoryResponse(
            incident_id=inc["incident_id"],
            mission_id=inc["mission_id"],
            incident_type=inc["incident_type"],
            severity=inc["severity"],
            start_ms=inc["start_ms"],
            end_ms=inc["end_ms"],
            peak_risk=inc["peak_risk"],
            phases=inc.get("phases", []),
            evidence=inc.get("evidence", []),
            root_causes=root_causes,
            recommended_mitigations=recommended,
            applied_mitigations=applied,
            outcomes=outcomes,
            source_phase=inc.get("source_phase", "phase4"),
            synced_at=inc.get("synced_at"),
        )

    async def find_similar_incidents(
        self,
        incident_id: str,
        limit: int = 20,
    ) -> SimilarHistoryResponse:
        """
        Find similar incidents based on deterministic matching.

        Args:
            incident_id: Query incident identifier.
            limit: Maximum results to return.

        Returns:
            SimilarHistoryResponse with matches.
        """
        # Enforce limits
        effective_limit = min(
            limit,
            settings.MEMORY_QUERY_MAX_LIMIT,
        )
        if effective_limit <= 0:
            effective_limit = settings.MEMORY_QUERY_DEFAULT_LIMIT

        data = await repository.find_similar_incidents(
            incident_id=incident_id,
            limit=effective_limit,
        )

        matches = []
        for m in data.get("matches", []):
            root_causes = [
                RootCauseInfo(
                    root_cause_id=rc.get("root_cause_id", ""),
                    classification=rc.get("classification", ""),
                    confidence=rc.get("confidence", 0.0),
                    reasoning_id=rc.get("reasoning_id"),
                    model=rc.get("model"),
                    prompt_version=rc.get("prompt_version"),
                    rationale=rc.get("rationale"),
                    uncertainties=rc.get("uncertainties", []),
                    source_phase=rc.get("source_phase", "phase5"),
                )
                for rc in m.get("root_causes", [])
            ]

            recommended = [
                MitigationInfo(
                    mitigation_id=mit["mitigation_id"],
                    description=mit["description"],
                    advisory_only=mit.get("advisory_only", True),
                    source=mit.get("source", "phase5_recommendation"),
                )
                for mit in m.get("recommended_mitigations", [])
            ]

            applied = [
                AppliedMitigationInfo(
                    application_id=a["application_id"],
                    mitigation_id=a["mitigation_id"],
                    description=a["description"],
                    applied_at=_parse_dt(a["applied_at"]),
                    recorded_by=a["recorded_by"],
                    notes=a.get("notes"),
                )
                for a in m.get("applied_mitigations", [])
            ]

            outcomes = [
                OutcomeInfo(
                    outcome_id=o["outcome_id"],
                    scope=OutcomeScope(o.get("scope", "incident")),
                    status=OutcomeStatus(o.get("status", "unknown")),
                    description=o["description"],
                    observed_at=_parse_dt(o["observed_at"]),
                    recorded_by=o.get("recorded_by", "unknown"),
                    source=o.get("source", "explicit_observation"),
                )
                for o in m.get("outcomes", [])
            ]

            matches.append(
                SimilarIncidentMatch(
                    incident_id=m["incident_id"],
                    mission_id=m["mission_id"],
                    incident_type=m["incident_type"],
                    severity=m["severity"],
                    start_ms=m["start_ms"],
                    end_ms=m["end_ms"],
                    peak_risk=m["peak_risk"],
                    root_causes=root_causes,
                    recommended_mitigations=recommended,
                    applied_mitigations=applied,
                    outcomes=outcomes,
                )
            )

        return SimilarHistoryResponse(
            query_incident_id=data["query_incident_id"],
            matches=matches,
            total=data["total"],
        )


# =============================================================================
# Internal Helpers
# =============================================================================

def _parse_dt(value: Any) -> datetime:
    """Parse a datetime from various formats."""
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            pass
        from .mapper import _parse_datetime
        return _parse_datetime(value)
    return datetime.now(timezone.utc)
