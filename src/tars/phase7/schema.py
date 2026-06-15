"""
Neo4j Schema Initialization
============================
Constraints and indexes for the Phase 7 operational memory graph.

All statements use IF NOT EXISTS so they are safe to run repeatedly.
"""

from __future__ import annotations

import logging

from .database import get_driver
from .config import settings

logger = logging.getLogger("phase7.schema")

# ---------------------------------------------------------------------------
# Uniqueness Constraints
# ---------------------------------------------------------------------------
CONSTRAINTS = [
    (
        "mission_id_unique",
        "CREATE CONSTRAINT mission_id_unique IF NOT EXISTS "
        "FOR (n:Mission) REQUIRE n.mission_id IS UNIQUE",
    ),
    (
        "incident_id_unique",
        "CREATE CONSTRAINT incident_id_unique IF NOT EXISTS "
        "FOR (n:Incident) REQUIRE n.incident_id IS UNIQUE",
    ),
    (
        "root_cause_id_unique",
        "CREATE CONSTRAINT root_cause_id_unique IF NOT EXISTS "
        "FOR (n:RootCause) REQUIRE n.root_cause_id IS UNIQUE",
    ),
    (
        "mitigation_id_unique",
        "CREATE CONSTRAINT mitigation_id_unique IF NOT EXISTS "
        "FOR (n:Mitigation) REQUIRE n.mitigation_id IS UNIQUE",
    ),
    (
        "outcome_id_unique",
        "CREATE CONSTRAINT outcome_id_unique IF NOT EXISTS "
        "FOR (n:Outcome) REQUIRE n.outcome_id IS UNIQUE",
    ),
    (
        "memory_sync_mission_id_unique",
        "CREATE CONSTRAINT memory_sync_mission_id_unique IF NOT EXISTS "
        "FOR (n:MemorySync) REQUIRE n.mission_id IS UNIQUE",
    ),
]

# ---------------------------------------------------------------------------
# Indexes
# ---------------------------------------------------------------------------
INDEXES = [
    (
        "incident_type_index",
        "CREATE INDEX incident_type_index IF NOT EXISTS "
        "FOR (n:Incident) ON (n.incident_type)",
    ),
    (
        "incident_severity_index",
        "CREATE INDEX incident_severity_index IF NOT EXISTS "
        "FOR (n:Incident) ON (n.severity)",
    ),
    (
        "root_cause_normalized_index",
        "CREATE INDEX root_cause_normalized_index IF NOT EXISTS "
        "FOR (n:RootCause) ON (n.normalized_classification)",
    ),
    (
        "mitigation_normalized_index",
        "CREATE INDEX mitigation_normalized_index IF NOT EXISTS "
        "FOR (n:Mitigation) ON (n.normalized_description)",
    ),
    (
        "outcome_status_index",
        "CREATE INDEX outcome_status_index IF NOT EXISTS "
        "FOR (n:Outcome) ON (n.status)",
    ),
    (
        "mission_start_time_index",
        "CREATE INDEX mission_start_time_index IF NOT EXISTS "
        "FOR (n:Mission) ON (n.start_time)",
    ),
]


async def init_schema() -> dict[str, int]:
    """
    Initialize all constraints and indexes.

    Safe to call repeatedly; uses IF NOT EXISTS for all statements.

    Returns:
        Dict with counts of constraints and indexes applied.
    """
    driver = get_driver()
    constraints_applied = 0
    indexes_applied = 0

    async with driver.session(database=settings.NEO4J_DATABASE) as session:
        for name, cypher in CONSTRAINTS:
            try:
                await session.run(cypher)
                constraints_applied += 1
                logger.debug("Constraint applied: %s", name)
            except Exception as exc:
                logger.warning(
                    "Failed to apply constraint '%s': %s", name, exc
                )

        for name, cypher in INDEXES:
            try:
                await session.run(cypher)
                indexes_applied += 1
                logger.debug("Index applied: %s", name)
            except Exception as exc:
                logger.warning(
                    "Failed to apply index '%s': %s", name, exc
                )

    logger.info(
        "Schema initialized: %d constraints, %d indexes",
        constraints_applied,
        indexes_applied,
    )
    return {
        "constraints": constraints_applied,
        "indexes": indexes_applied,
    }


async def check_schema_ready() -> bool:
    """
    Check if all required constraints exist.

    Returns:
        True if all constraints are present, False otherwise.
    """
    driver = get_driver()
    try:
        async with driver.session(database=settings.NEO4J_DATABASE) as session:
            result = await session.run("SHOW CONSTRAINTS")
            records = await result.data()
            existing_names = {r.get("name", "") for r in records}

            required_names = {name for name, _ in CONSTRAINTS}
            return required_names.issubset(existing_names)
    except Exception as exc:
        logger.warning("Schema readiness check failed: %s", exc)
        return False
