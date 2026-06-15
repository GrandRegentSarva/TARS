"""
Phase 7 Graph Repository
=========================
Parameterized Cypher operations for the Neo4j operational memory graph.

All Cypher uses parameters only -- never string interpolation of user input.

Responsibilities:
- Schema initialization
- Mission projection upserts (single transaction)
- Explicit observation recording (mitigations, outcomes)
- Incident neighborhood queries
- Similar-history queries
- Sync status management
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from neo4j import AsyncTransaction

from .config import settings
from .database import execute_read, execute_write_transaction, get_driver
from .models import (
    AnalysisRelationship,
    AppliedMitigationInfo,
    IncidentMemoryResponse,
    IncidentRecord,
    MitigationInfo,
    MitigationRecord,
    MissionProjection,
    MissionRecord,
    OutcomeInfo,
    OutcomeRecord,
    RootCauseInfo,
    RootCauseRecord,
    RecommendationRelationship,
    SimilarIncidentMatch,
    SyncCounts,
    SyncStatus,
)

logger = logging.getLogger("phase7.repository")


# =============================================================================
# Mission Projection (Single Transaction)
# =============================================================================

async def project_mission(projection: MissionProjection) -> SyncCounts:
    """
    Write a complete mission projection in one Neo4j transaction.

    Uses MERGE on stable identities to ensure idempotency.
    Updates source-owned properties without deleting explicit observations.

    Args:
        projection: Complete mission projection data.

    Returns:
        SyncCounts with projection statistics.
    """
    counts = SyncCounts()

    async def _work(tx: AsyncTransaction) -> SyncCounts:
        nonlocal counts
        now = datetime.now(timezone.utc).isoformat()

        # 1. Upsert Mission node
        await tx.run(
            """
            MERGE (m:Mission {mission_id: $mission_id})
            SET m.drone_id = $drone_id,
                m.start_time = $start_time,
                m.end_time = $end_time,
                m.mission_result = $mission_result,
                m.source_phase = $source_phase,
                m.source_updated_at = $source_updated_at,
                m.synced_at = $synced_at
            """,
            {
                "mission_id": projection.mission.mission_id,
                "drone_id": projection.mission.drone_id,
                "start_time": projection.mission.start_time.isoformat(),
                "end_time": projection.mission.end_time.isoformat() if projection.mission.end_time else None,
                "mission_result": projection.mission.mission_result,
                "source_phase": projection.mission.source_phase,
                "source_updated_at": projection.mission.source_updated_at.isoformat() if projection.mission.source_updated_at else None,
                "synced_at": now,
            },
        )
        counts.missions = 1

        # 2. Upsert Incident nodes and EXPERIENCED relationships
        for inc in projection.incidents:
            await tx.run(
                """
                MERGE (i:Incident {incident_id: $incident_id})
                SET i.mission_id = $mission_id,
                    i.incident_type = $incident_type,
                    i.severity = $severity,
                    i.start_ms = $start_ms,
                    i.end_ms = $end_ms,
                    i.peak_risk = $peak_risk,
                    i.phases = $phases,
                    i.evidence = $evidence,
                    i.source_phase = $source_phase,
                    i.synced_at = $synced_at
                WITH i
                MATCH (m:Mission {mission_id: $mission_id})
                MERGE (m)-[:EXPERIENCED]->(i)
                """,
                {
                    "incident_id": inc.incident_id,
                    "mission_id": inc.mission_id,
                    "incident_type": inc.incident_type,
                    "severity": inc.severity,
                    "start_ms": inc.start_ms,
                    "end_ms": inc.end_ms,
                    "peak_risk": inc.peak_risk,
                    "phases": inc.phases,
                    "evidence": inc.evidence,
                    "source_phase": inc.source_phase,
                    "synced_at": now,
                },
            )
            counts.incidents += 1

        # 3. Upsert RootCause nodes
        for rc in projection.root_causes:
            await tx.run(
                """
                MERGE (rc:RootCause {root_cause_id: $root_cause_id})
                SET rc.classification = $classification,
                    rc.normalized_classification = $normalized_classification,
                    rc.source_phase = $source_phase
                """,
                {
                    "root_cause_id": rc.root_cause_id,
                    "classification": rc.classification,
                    "normalized_classification": rc.normalized_classification,
                    "source_phase": rc.source_phase,
                },
            )
            counts.root_causes += 1

        # 4. Upsert Mitigation nodes (from recommendations)
        for mit in projection.mitigations:
            await tx.run(
                """
                MERGE (mit:Mitigation {mitigation_id: $mitigation_id})
                SET mit.description = $description,
                    mit.normalized_description = $normalized_description,
                    mit.advisory_only = $advisory_only,
                    mit.source = $source
                """,
                {
                    "mitigation_id": mit.mitigation_id,
                    "description": mit.description,
                    "normalized_description": mit.normalized_description,
                    "advisory_only": mit.advisory_only,
                    "source": mit.source,
                },
            )
            counts.mitigations += 1

        # 5. Create ANALYZED_AS relationships (merge on reasoning_id)
        for analysis in projection.analyses:
            await tx.run(
                """
                MATCH (i:Incident {incident_id: $incident_id})
                MATCH (rc:RootCause {root_cause_id: $root_cause_id})
                MERGE (i)-[r:ANALYZED_AS {reasoning_id: $reasoning_id}]->(rc)
                SET r.confidence = $confidence,
                    r.model = $model,
                    r.prompt_version = $prompt_version,
                    r.rationale = $rationale,
                    r.uncertainties = $uncertainties,
                    r.created_at = $created_at,
                    r.phoenix_trace_id = $phoenix_trace_id
                """,
                {
                    "incident_id": analysis.incident_id,
                    "root_cause_id": analysis.root_cause_id,
                    "reasoning_id": analysis.reasoning_id,
                    "confidence": analysis.confidence,
                    "model": analysis.model,
                    "prompt_version": analysis.prompt_version,
                    "rationale": analysis.rationale,
                    "uncertainties": analysis.uncertainties,
                    "created_at": analysis.created_at,
                    "phoenix_trace_id": analysis.phoenix_trace_id,
                },
            )
            counts.relationships += 1

        # 6. Create RECOMMENDED relationships (merge on reasoning_id)
        for rec in projection.recommendations:
            await tx.run(
                """
                MATCH (i:Incident {incident_id: $incident_id})
                MATCH (mit:Mitigation {mitigation_id: $mitigation_id})
                MERGE (i)-[r:RECOMMENDED {reasoning_id: $reasoning_id}]->(mit)
                SET r.recommended_at = $recommended_at,
                    r.advisory_only = $advisory_only
                """,
                {
                    "incident_id": rec.incident_id,
                    "mitigation_id": rec.mitigation_id,
                    "reasoning_id": rec.reasoning_id,
                    "recommended_at": rec.recommended_at,
                    "advisory_only": rec.advisory_only,
                },
            )
            counts.relationships += 1

        # 7. Upsert mission-scoped outcome if present
        if projection.mission_outcome:
            outcome = projection.mission_outcome
            await tx.run(
                """
                MERGE (o:Outcome {outcome_id: $outcome_id})
                SET o.scope = $scope,
                    o.status = $status,
                    o.description = $description,
                    o.observed_at = $observed_at,
                    o.source = $source,
                    o.recorded_by = $recorded_by
                WITH o
                MATCH (m:Mission {mission_id: $mission_id})
                MERGE (m)-[:RESULTED_IN]->(o)
                """,
                {
                    "outcome_id": outcome.outcome_id,
                    "scope": outcome.scope,
                    "status": outcome.status,
                    "description": outcome.description,
                    "observed_at": outcome.observed_at.isoformat(),
                    "source": outcome.source,
                    "recorded_by": outcome.recorded_by,
                    "mission_id": projection.mission.mission_id,
                },
            )
            counts.outcomes += 1

        return counts

    counts = await execute_write_transaction(_work)
    return counts


# =============================================================================
# Explicit Observation Recording
# =============================================================================

async def record_applied_mitigation(
    incident_id: str,
    application_id: str,
    description: str,
    normalized_description: str,
    mitigation_id: str,
    applied_at: datetime,
    recorded_by: str,
    notes: Optional[str] = None,
) -> dict[str, Any]:
    """
    Record an explicitly applied mitigation.

    Creates or links a Mitigation node through APPLIED relationship.

    Returns:
        Dict with application details and whether it was newly created.
    """
    result: dict[str, Any] = {}

    async def _work(tx: AsyncTransaction) -> dict[str, Any]:
        # Check if idempotency key already exists
        existing = await tx.run(
            """
            MATCH (i:Incident)-[r:APPLIED {application_id: $application_id}]->(mit:Mitigation)
            RETURN r.application_id AS application_id,
                   i.incident_id AS incident_id,
                   mit.mitigation_id AS mitigation_id,
                   mit.description AS description,
                   r.applied_at AS applied_at,
                   r.recorded_by AS recorded_by,
                   r.notes AS notes
            """,
            {"application_id": application_id},
        )
        existing_records = await existing.data()

        if existing_records:
            rec = existing_records[0]
            return {
                "application_id": rec["application_id"],
                "incident_id": rec["incident_id"],
                "mitigation_id": rec["mitigation_id"],
                "description": rec["description"],
                "applied_at": rec["applied_at"],
                "recorded_by": rec["recorded_by"],
                "notes": rec.get("notes"),
                "created": False,
            }

        # Verify incident exists
        inc_check = await tx.run(
            "MATCH (i:Incident {incident_id: $incident_id}) RETURN i.incident_id AS id",
            {"incident_id": incident_id},
        )
        inc_records = await inc_check.data()
        if not inc_records:
            raise ValueError(f"Incident '{incident_id}' not found in graph")

        # Upsert Mitigation node
        await tx.run(
            """
            MERGE (mit:Mitigation {mitigation_id: $mitigation_id})
            ON CREATE SET mit.description = $description,
                          mit.normalized_description = $normalized_description,
                          mit.advisory_only = false,
                          mit.source = 'explicit_observation'
            """,
            {
                "mitigation_id": mitigation_id,
                "description": description,
                "normalized_description": normalized_description,
            },
        )

        # Create APPLIED relationship
        await tx.run(
            """
            MATCH (i:Incident {incident_id: $incident_id})
            MATCH (mit:Mitigation {mitigation_id: $mitigation_id})
            MERGE (i)-[r:APPLIED {application_id: $application_id}]->(mit)
            SET r.applied_at = $applied_at,
                r.recorded_by = $recorded_by,
                r.notes = $notes
            """,
            {
                "incident_id": incident_id,
                "mitigation_id": mitigation_id,
                "application_id": application_id,
                "applied_at": applied_at.isoformat(),
                "recorded_by": recorded_by,
                "notes": notes,
            },
        )

        return {
            "application_id": application_id,
            "incident_id": incident_id,
            "mitigation_id": mitigation_id,
            "description": description,
            "applied_at": applied_at.isoformat(),
            "recorded_by": recorded_by,
            "notes": notes,
            "created": True,
        }

    result = await execute_write_transaction(_work)
    return result


async def record_outcome(
    incident_id: str,
    outcome_id: str,
    scope: str,
    status: str,
    description: str,
    observed_at: datetime,
    recorded_by: str,
    mitigation_application_id: Optional[str] = None,
) -> dict[str, Any]:
    """
    Record an explicit outcome observation.

    Creates an Outcome node and connects it to the incident.
    Optionally creates a temporal FOLLOWED_BY from a mitigation.

    Returns:
        Dict with outcome details and whether it was newly created.
    """

    async def _work(tx: AsyncTransaction) -> dict[str, Any]:
        # Check if idempotency key already exists
        existing = await tx.run(
            """
            MATCH (i:Incident)-[:RESULTED_IN]->(o:Outcome {outcome_id: $outcome_id})
            RETURN o.outcome_id AS outcome_id,
                   i.incident_id AS incident_id,
                   o.scope AS scope,
                   o.status AS status,
                   o.description AS description,
                   o.observed_at AS observed_at,
                   o.recorded_by AS recorded_by
            """,
            {"outcome_id": outcome_id},
        )
        existing_records = await existing.data()

        if existing_records:
            rec = existing_records[0]
            return {
                "outcome_id": rec["outcome_id"],
                "incident_id": rec["incident_id"],
                "scope": rec["scope"],
                "status": rec["status"],
                "description": rec["description"],
                "observed_at": rec["observed_at"],
                "recorded_by": rec["recorded_by"],
                "mitigation_application_id": mitigation_application_id,
                "created": False,
            }

        # Verify incident exists
        inc_check = await tx.run(
            "MATCH (i:Incident {incident_id: $incident_id}) RETURN i.incident_id AS id",
            {"incident_id": incident_id},
        )
        inc_records = await inc_check.data()
        if not inc_records:
            raise ValueError(f"Incident '{incident_id}' not found in graph")

        # Create Outcome node
        await tx.run(
            """
            MERGE (o:Outcome {outcome_id: $outcome_id})
            SET o.scope = $scope,
                o.status = $status,
                o.description = $description,
                o.observed_at = $observed_at,
                o.source = 'explicit_observation',
                o.recorded_by = $recorded_by
            """,
            {
                "outcome_id": outcome_id,
                "scope": scope,
                "status": status,
                "description": description,
                "observed_at": observed_at.isoformat(),
                "recorded_by": recorded_by,
            },
        )

        # Connect to incident
        await tx.run(
            """
            MATCH (i:Incident {incident_id: $incident_id})
            MATCH (o:Outcome {outcome_id: $outcome_id})
            MERGE (i)-[:RESULTED_IN]->(o)
            """,
            {
                "incident_id": incident_id,
                "outcome_id": outcome_id,
            },
        )

        # Optional temporal FOLLOWED_BY from mitigation
        if mitigation_application_id:
            # Verify the mitigation application exists before creating FOLLOWED_BY
            mit_check = await tx.run(
                """
                MATCH (i:Incident {incident_id: $incident_id})-[r:APPLIED {application_id: $application_id}]->(mit:Mitigation)
                RETURN mit.mitigation_id AS mitigation_id
                """,
                {
                    "incident_id": incident_id,
                    "application_id": mitigation_application_id,
                },
            )
            mit_records = await mit_check.data()
            if not mit_records:
                raise ValueError(
                    f"Mitigation application '{mitigation_application_id}' "
                    f"not found for incident '{incident_id}'"
                )

            await tx.run(
                """
                MATCH (i:Incident {incident_id: $incident_id})-[r:APPLIED {application_id: $application_id}]->(mit:Mitigation)
                MATCH (o:Outcome {outcome_id: $outcome_id})
                MERGE (mit)-[:FOLLOWED_BY]->(o)
                """,
                {
                    "incident_id": incident_id,
                    "application_id": mitigation_application_id,
                    "outcome_id": outcome_id,
                },
            )

        return {
            "outcome_id": outcome_id,
            "incident_id": incident_id,
            "scope": scope,
            "status": status,
            "description": description,
            "observed_at": observed_at.isoformat(),
            "recorded_by": recorded_by,
            "mitigation_application_id": mitigation_application_id,
            "created": True,
        }

    return await execute_write_transaction(_work)


# =============================================================================
# Sync Status Management
# =============================================================================

async def upsert_sync_status(
    mission_id: str,
    status: str,
    started_at: datetime,
    completed_at: Optional[datetime] = None,
    counts: Optional[SyncCounts] = None,
    error_code: Optional[str] = None,
    error_message: Optional[str] = None,
) -> None:
    """Upsert the MemorySync node for a mission."""

    async def _work(tx: AsyncTransaction) -> None:
        await tx.run(
            """
            MERGE (s:MemorySync {mission_id: $mission_id})
            SET s.status = $status,
                s.started_at = $started_at,
                s.completed_at = $completed_at,
                s.counts_missions = $counts_missions,
                s.counts_incidents = $counts_incidents,
                s.counts_root_causes = $counts_root_causes,
                s.counts_mitigations = $counts_mitigations,
                s.counts_outcomes = $counts_outcomes,
                s.counts_relationships = $counts_relationships,
                s.counts_analyses_skipped = $counts_analyses_skipped,
                s.error_code = $error_code,
                s.error_message = $error_message
            """,
            {
                "mission_id": mission_id,
                "status": status,
                "started_at": started_at.isoformat(),
                "completed_at": completed_at.isoformat() if completed_at else None,
                "counts_missions": counts.missions if counts else 0,
                "counts_incidents": counts.incidents if counts else 0,
                "counts_root_causes": counts.root_causes if counts else 0,
                "counts_mitigations": counts.mitigations if counts else 0,
                "counts_outcomes": counts.outcomes if counts else 0,
                "counts_relationships": counts.relationships if counts else 0,
                "counts_analyses_skipped": counts.analyses_skipped if counts else 0,
                "error_code": error_code,
                "error_message": _truncate_error(error_message),
            },
        )

    await execute_write_transaction(_work)


async def get_sync_status(mission_id: str) -> Optional[dict[str, Any]]:
    """Get the sync status for a mission."""
    records = await execute_read(
        """
        MATCH (s:MemorySync {mission_id: $mission_id})
        RETURN s.mission_id AS mission_id,
               s.status AS status,
               s.started_at AS started_at,
               s.completed_at AS completed_at,
               s.counts_missions AS counts_missions,
               s.counts_incidents AS counts_incidents,
               s.counts_root_causes AS counts_root_causes,
               s.counts_mitigations AS counts_mitigations,
               s.counts_outcomes AS counts_outcomes,
               s.counts_relationships AS counts_relationships,
               s.counts_analyses_skipped AS counts_analyses_skipped,
               s.error_code AS error_code,
               s.error_message AS error_message
        """,
        {"mission_id": mission_id},
    )

    if not records:
        return None

    return records[0]


# =============================================================================
# Incident Neighborhood Query
# =============================================================================

async def get_incident_neighborhood(
    incident_id: str,
) -> Optional[dict[str, Any]]:
    """
    Get the bounded graph neighborhood for one incident.

    Returns incident facts, root causes, recommendations,
    applied mitigations, and outcomes.
    """
    # Get incident node
    incident_records = await execute_read(
        """
        MATCH (i:Incident {incident_id: $incident_id})
        OPTIONAL MATCH (m:Mission)-[:EXPERIENCED]->(i)
        RETURN i.incident_id AS incident_id,
               i.mission_id AS mission_id,
               i.incident_type AS incident_type,
               i.severity AS severity,
               i.start_ms AS start_ms,
               i.end_ms AS end_ms,
               i.peak_risk AS peak_risk,
               i.phases AS phases,
               i.evidence AS evidence,
               i.source_phase AS source_phase,
               i.synced_at AS synced_at
        """,
        {"incident_id": incident_id},
    )

    if not incident_records:
        return None

    inc = incident_records[0]

    # Get root causes via ANALYZED_AS
    root_causes = await execute_read(
        """
        MATCH (i:Incident {incident_id: $incident_id})-[r:ANALYZED_AS]->(rc:RootCause)
        RETURN rc.root_cause_id AS root_cause_id,
               rc.classification AS classification,
               r.confidence AS confidence,
               r.reasoning_id AS reasoning_id,
               r.model AS model,
               r.prompt_version AS prompt_version,
               r.rationale AS rationale,
               r.uncertainties AS uncertainties,
               rc.source_phase AS source_phase
        """,
        {"incident_id": incident_id},
    )

    # Get recommended mitigations via RECOMMENDED
    recommended = await execute_read(
        """
        MATCH (i:Incident {incident_id: $incident_id})-[r:RECOMMENDED]->(mit:Mitigation)
        RETURN mit.mitigation_id AS mitigation_id,
               mit.description AS description,
               mit.advisory_only AS advisory_only,
               mit.source AS source
        """,
        {"incident_id": incident_id},
    )

    # Get applied mitigations via APPLIED
    applied = await execute_read(
        """
        MATCH (i:Incident {incident_id: $incident_id})-[r:APPLIED]->(mit:Mitigation)
        RETURN r.application_id AS application_id,
               mit.mitigation_id AS mitigation_id,
               mit.description AS description,
               r.applied_at AS applied_at,
               r.recorded_by AS recorded_by,
               r.notes AS notes
        """,
        {"incident_id": incident_id},
    )

    # Get outcomes via RESULTED_IN
    outcomes = await execute_read(
        """
        MATCH (i:Incident {incident_id: $incident_id})-[:RESULTED_IN]->(o:Outcome)
        RETURN o.outcome_id AS outcome_id,
               o.scope AS scope,
               o.status AS status,
               o.description AS description,
               o.observed_at AS observed_at,
               o.recorded_by AS recorded_by,
               o.source AS source
        """,
        {"incident_id": incident_id},
    )

    return {
        "incident": inc,
        "root_causes": root_causes,
        "recommended_mitigations": recommended,
        "applied_mitigations": applied,
        "outcomes": outcomes,
    }


# =============================================================================
# Similar History Query
# =============================================================================

async def find_similar_incidents(
    incident_id: str,
    limit: int = 20,
) -> dict[str, Any]:
    """
    Find similar incidents based on deterministic matching.

    Similarity criteria:
    1. Same incident_type
    2. Exclude the current incident
    3. Rank by severity match, shared root-cause classification, then recency

    Returns:
        Dict with query_incident_id, matches list, and total count.
    """
    # First get the query incident's type and severity
    query_records = await execute_read(
        """
        MATCH (i:Incident {incident_id: $incident_id})
        RETURN i.incident_type AS incident_type,
               i.severity AS severity
        """,
        {"incident_id": incident_id},
    )

    if not query_records:
        return {
            "query_incident_id": incident_id,
            "matches": [],
            "total": 0,
        }

    query_type = query_records[0]["incident_type"]
    query_severity = query_records[0]["severity"]

    # Get root cause classifications for the query incident
    query_rc_records = await execute_read(
        """
        MATCH (i:Incident {incident_id: $incident_id})-[:ANALYZED_AS]->(rc:RootCause)
        RETURN rc.normalized_classification AS nc
        """,
        {"incident_id": incident_id},
    )
    query_root_causes = {r["nc"] for r in query_rc_records}

    # Find similar incidents by type, excluding self
    # Rank by: severity match, shared root-cause count, then recency
    similar_records = await execute_read(
        """
        MATCH (i:Incident {incident_type: $incident_type})
        WHERE i.incident_id <> $incident_id
        OPTIONAL MATCH (m:Mission)-[:EXPERIENCED]->(i)
        OPTIONAL MATCH (i)-[aa:ANALYZED_AS]->(rc:RootCause)
        WITH i, m,
             collect(DISTINCT {
                 root_cause_id: rc.root_cause_id,
                 classification: rc.classification,
                 confidence: aa.confidence,
                 reasoning_id: aa.reasoning_id,
                 model: aa.model,
                 prompt_version: aa.prompt_version,
                 rationale: aa.rationale,
                 uncertainties: aa.uncertainties,
                 source_phase: rc.source_phase,
                 normalized_classification: rc.normalized_classification
             }) AS root_causes,
             collect(DISTINCT rc.normalized_classification) AS rc_classifications
        WITH i, m, root_causes, rc_classifications,
             CASE WHEN i.severity = $query_severity THEN 1 ELSE 0 END AS severity_match,
             size([nc IN rc_classifications WHERE nc IN $query_root_causes]) AS shared_rc_count
        RETURN i.incident_id AS incident_id,
               i.mission_id AS mission_id,
               i.incident_type AS incident_type,
               i.severity AS severity,
               i.start_ms AS start_ms,
               i.end_ms AS end_ms,
               i.peak_risk AS peak_risk,
               i.synced_at AS synced_at,
               root_causes,
               severity_match,
               shared_rc_count
        ORDER BY severity_match DESC, shared_rc_count DESC, i.synced_at DESC
        LIMIT $limit
        """,
        {
            "incident_type": query_type,
            "incident_id": incident_id,
            "query_severity": query_severity,
            "query_root_causes": list(query_root_causes),
            "limit": limit,
        },
    )

    matches = []
    for rec in similar_records:
        sim_incident_id = rec["incident_id"]

        # Filter out null root causes from the collect
        raw_rcs = rec.get("root_causes", [])
        root_causes = [
            rc for rc in raw_rcs
            if rc.get("root_cause_id") is not None
        ]

        # Get recommended mitigations
        recommended = await execute_read(
            """
            MATCH (i:Incident {incident_id: $incident_id})-[:RECOMMENDED]->(mit:Mitigation)
            RETURN mit.mitigation_id AS mitigation_id,
                   mit.description AS description,
                   mit.advisory_only AS advisory_only,
                   mit.source AS source
            """,
            {"incident_id": sim_incident_id},
        )

        # Get applied mitigations
        applied = await execute_read(
            """
            MATCH (i:Incident {incident_id: $incident_id})-[r:APPLIED]->(mit:Mitigation)
            RETURN r.application_id AS application_id,
                   mit.mitigation_id AS mitigation_id,
                   mit.description AS description,
                   r.applied_at AS applied_at,
                   r.recorded_by AS recorded_by,
                   r.notes AS notes
            """,
            {"incident_id": sim_incident_id},
        )

        # Get outcomes
        outcomes = await execute_read(
            """
            MATCH (i:Incident {incident_id: $incident_id})-[:RESULTED_IN]->(o:Outcome)
            RETURN o.outcome_id AS outcome_id,
                   o.scope AS scope,
                   o.status AS status,
                   o.description AS description,
                   o.observed_at AS observed_at,
                   o.recorded_by AS recorded_by,
                   o.source AS source
            """,
            {"incident_id": sim_incident_id},
        )

        matches.append({
            "incident_id": sim_incident_id,
            "mission_id": rec["mission_id"],
            "incident_type": rec["incident_type"],
            "severity": rec["severity"],
            "start_ms": rec["start_ms"],
            "end_ms": rec["end_ms"],
            "peak_risk": rec["peak_risk"],
            "root_causes": root_causes,
            "recommended_mitigations": recommended,
            "applied_mitigations": applied,
            "outcomes": outcomes,
        })

    return {
        "query_incident_id": incident_id,
        "matches": matches,
        "total": len(matches),
    }


# =============================================================================
# Incident Existence Check
# =============================================================================

async def incident_exists(incident_id: str) -> bool:
    """Check if an incident node exists in the graph."""
    records = await execute_read(
        "MATCH (i:Incident {incident_id: $incident_id}) RETURN i.incident_id AS id",
        {"incident_id": incident_id},
    )
    return len(records) > 0


# =============================================================================
# Internal Helpers
# =============================================================================

def _truncate_error(message: Optional[str], max_len: int = 500) -> Optional[str]:
    """Truncate error messages to a bounded length, removing credentials."""
    if message is None:
        return None
    # Remove potential credential patterns
    import re
    sanitized = re.sub(r"(password|token|key|secret)=[^\s&]+", r"\1=***", message, flags=re.IGNORECASE)
    if len(sanitized) > max_len:
        return sanitized[:max_len] + "..."
    return sanitized
