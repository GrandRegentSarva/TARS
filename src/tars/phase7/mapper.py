"""
Phase 7 Mapper
==============
Pure normalization, deterministic ID generation, and graph-write input mapping.

All functions are pure (no I/O, no side effects) and independently testable.

Responsibilities:
- Normalize root-cause and mitigation text deterministically.
- Generate stable IDs from normalized text using SHA-256.
- Map Phase 2, Phase 4, and Phase 5 API responses into graph record inputs.
- Map mission results into mission-scoped outcomes.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Any, Optional

from .models import (
    AnalysisRelationship,
    IncidentRecord,
    MissionProjection,
    MissionRecord,
    MitigationRecord,
    OutcomeRecord,
    RecommendationRelationship,
    RootCauseRecord,
)


# =============================================================================
# Text Normalization
# =============================================================================

def normalize_text(text: str) -> str:
    """
    Normalize text for deterministic comparison and ID generation.

    - Strip leading/trailing whitespace
    - Convert to lower case
    - Collapse multiple whitespace characters into single spaces

    Args:
        text: Raw text to normalize.

    Returns:
        Normalized text string.
    """
    stripped = text.strip()
    lowered = stripped.lower()
    collapsed = re.sub(r"\s+", " ", lowered)
    return collapsed


# =============================================================================
# Deterministic ID Generation
# =============================================================================

def generate_deterministic_id(prefix: str, normalized_text: str) -> str:
    """
    Generate a stable ID from normalized text using SHA-256.

    The ID format is: {prefix}_{first 16 hex chars of SHA-256}

    Args:
        prefix: ID prefix (e.g., 'rc' for root cause, 'mit' for mitigation).
        normalized_text: Already-normalized text to hash.

    Returns:
        Deterministic ID string.
    """
    digest = hashlib.sha256(normalized_text.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}_{digest}"


def generate_outcome_id_from_mission(
    mission_id: str,
    mission_result: str,
) -> str:
    """
    Generate a deterministic outcome ID for a mission result.

    Args:
        mission_id: Phase 2 mission identifier.
        mission_result: Phase 2 mission result string.

    Returns:
        Deterministic outcome ID.
    """
    source = f"{mission_id}:{mission_result}"
    digest = hashlib.sha256(source.encode("utf-8")).hexdigest()[:16]
    return f"outcome_mission_{digest}"


# =============================================================================
# Phase 2 Mission Mapping
# =============================================================================

def map_mission(mission_data: dict[str, Any]) -> MissionRecord:
    """
    Map a Phase 2 mission detail response into a MissionRecord.

    Args:
        mission_data: Phase 2 mission detail dict.

    Returns:
        MissionRecord ready for graph projection.

    Raises:
        ValueError: If required fields are missing.
    """
    _require_fields(mission_data, ["mission_id", "drone_id", "start_time", "mission_result"])

    start_time = _parse_datetime(mission_data["start_time"])
    end_time = _parse_datetime(mission_data.get("end_time")) if mission_data.get("end_time") else None
    source_updated_at = _parse_datetime(mission_data.get("created_at")) if mission_data.get("created_at") else None

    return MissionRecord(
        mission_id=mission_data["mission_id"],
        drone_id=mission_data["drone_id"],
        start_time=start_time,
        end_time=end_time,
        mission_result=mission_data["mission_result"],
        source_phase="phase2",
        source_updated_at=source_updated_at,
    )


def map_mission_outcome(mission_data: dict[str, Any]) -> Optional[OutcomeRecord]:
    """
    Map a Phase 2 mission result into a mission-scoped outcome.

    Only creates an outcome if the mission has a result.

    Args:
        mission_data: Phase 2 mission detail dict.

    Returns:
        OutcomeRecord for the mission result, or None.
    """
    mission_result = mission_data.get("mission_result")
    if not mission_result:
        return None

    mission_id = mission_data["mission_id"]
    outcome_id = generate_outcome_id_from_mission(mission_id, mission_result)

    # Map mission result to controlled outcome status
    status = _mission_result_to_outcome_status(mission_result)

    return OutcomeRecord(
        outcome_id=outcome_id,
        scope="mission",
        status=status,
        description=f"Mission result: {mission_result}",
        observed_at=_parse_datetime(mission_data.get("end_time") or mission_data["start_time"]),
        source="phase2_mission_result",
        recorded_by="phase2",
    )


# =============================================================================
# Phase 4 Incident Mapping
# =============================================================================

def map_incident(incident_data: dict[str, Any]) -> IncidentRecord:
    """
    Map a Phase 4 incident into an IncidentRecord.

    Args:
        incident_data: Phase 4 incident dict.

    Returns:
        IncidentRecord ready for graph projection.

    Raises:
        ValueError: If required fields are missing.
    """
    _require_fields(
        incident_data,
        ["incident_id", "mission_id", "incident_type", "severity", "start_ms", "end_ms"],
    )

    return IncidentRecord(
        incident_id=incident_data["incident_id"],
        mission_id=incident_data["mission_id"],
        incident_type=incident_data["incident_type"],
        severity=incident_data["severity"],
        start_ms=incident_data["start_ms"],
        end_ms=incident_data["end_ms"],
        peak_risk=float(incident_data.get("peak_risk", 0.0)),
        phases=incident_data.get("phases", []),
        evidence=incident_data.get("evidence", []),
        source_phase="phase4",
    )


def map_incidents(incidents_data: list[dict[str, Any]]) -> list[IncidentRecord]:
    """Map a list of Phase 4 incidents into IncidentRecords."""
    return [map_incident(inc) for inc in incidents_data]


# =============================================================================
# Phase 5 Reasoning Mapping
# =============================================================================

def map_reasoning(
    reasoning_data: dict[str, Any],
) -> tuple[
    RootCauseRecord,
    MitigationRecord,
    AnalysisRelationship,
    RecommendationRelationship,
]:
    """
    Map a Phase 5 reasoning result into graph records.

    Produces:
    - A RootCause node record
    - A Mitigation node record (from the recommendation)
    - An ANALYZED_AS relationship
    - A RECOMMENDED relationship

    Args:
        reasoning_data: Phase 5 reasoning result dict.

    Returns:
        Tuple of (RootCauseRecord, MitigationRecord,
                  AnalysisRelationship, RecommendationRelationship).

    Raises:
        ValueError: If required fields are missing.
    """
    _require_fields(
        reasoning_data,
        [
            "reasoning_id", "incident_id", "root_cause", "confidence",
            "recommendation", "model", "prompt_version", "rationale",
            "created_at",
        ],
    )

    # Root cause
    normalized_rc = normalize_text(reasoning_data["root_cause"])
    root_cause_id = generate_deterministic_id("rc", normalized_rc)

    root_cause = RootCauseRecord(
        root_cause_id=root_cause_id,
        classification=reasoning_data["root_cause"],
        normalized_classification=normalized_rc,
        source_phase="phase5",
    )

    # Mitigation (from recommendation)
    normalized_mit = normalize_text(reasoning_data["recommendation"])
    mitigation_id = generate_deterministic_id("mit", normalized_mit)

    mitigation = MitigationRecord(
        mitigation_id=mitigation_id,
        description=reasoning_data["recommendation"],
        normalized_description=normalized_mit,
        advisory_only=reasoning_data.get("advisory_only", True),
        source="phase5_recommendation",
    )

    # ANALYZED_AS relationship
    analysis = AnalysisRelationship(
        incident_id=reasoning_data["incident_id"],
        root_cause_id=root_cause_id,
        reasoning_id=reasoning_data["reasoning_id"],
        confidence=reasoning_data["confidence"],
        model=reasoning_data["model"],
        prompt_version=reasoning_data["prompt_version"],
        rationale=reasoning_data["rationale"],
        uncertainties=reasoning_data.get("uncertainties", []),
        created_at=reasoning_data["created_at"],
        phoenix_trace_id=reasoning_data.get("phoenix_trace_id"),
    )

    # RECOMMENDED relationship
    recommendation = RecommendationRelationship(
        incident_id=reasoning_data["incident_id"],
        mitigation_id=mitigation_id,
        reasoning_id=reasoning_data["reasoning_id"],
        recommended_at=reasoning_data["created_at"],
        advisory_only=reasoning_data.get("advisory_only", True),
    )

    return root_cause, mitigation, analysis, recommendation


def map_all_reasoning(
    reasoning_list: list[dict[str, Any]],
) -> tuple[
    list[RootCauseRecord],
    list[MitigationRecord],
    list[AnalysisRelationship],
    list[RecommendationRelationship],
]:
    """
    Map all Phase 5 reasoning results for a mission.

    Deduplicates root causes and mitigations by their deterministic IDs.

    Args:
        reasoning_list: List of Phase 5 reasoning result dicts.

    Returns:
        Tuple of deduplicated lists.
    """
    root_causes: dict[str, RootCauseRecord] = {}
    mitigations: dict[str, MitigationRecord] = {}
    analyses: list[AnalysisRelationship] = []
    recommendations: list[RecommendationRelationship] = []

    for reasoning_data in reasoning_list:
        rc, mit, analysis, rec = map_reasoning(reasoning_data)

        # Deduplicate by ID (first occurrence wins for node properties)
        if rc.root_cause_id not in root_causes:
            root_causes[rc.root_cause_id] = rc
        if mit.mitigation_id not in mitigations:
            mitigations[mit.mitigation_id] = mit

        analyses.append(analysis)
        recommendations.append(rec)

    return (
        list(root_causes.values()),
        list(mitigations.values()),
        analyses,
        recommendations,
    )


# =============================================================================
# Full Mission Projection
# =============================================================================

def build_mission_projection(
    mission_data: dict[str, Any],
    incidents_data: list[dict[str, Any]],
    reasoning_list: Optional[list[dict[str, Any]]] = None,
) -> MissionProjection:
    """
    Build a complete mission projection from upstream API data.

    Validates that reasoning results reference incidents that exist in the
    fetched incident set. Reasoning referencing unknown incidents is skipped
    to prevent orphaned graph nodes.

    Args:
        mission_data: Phase 2 mission detail dict.
        incidents_data: List of Phase 4 incident dicts.
        reasoning_list: Optional list of Phase 5 reasoning result dicts.

    Returns:
        MissionProjection ready for a single graph transaction.
    """
    import logging as _logging
    _logger = _logging.getLogger("phase7.mapper")

    mission = map_mission(mission_data)
    incidents = map_incidents(incidents_data)
    mission_outcome = map_mission_outcome(mission_data)

    # Build set of known incident IDs for cross-validation
    known_incident_ids = {inc.incident_id for inc in incidents}

    root_causes: list[RootCauseRecord] = []
    mitigations_list: list[MitigationRecord] = []
    analyses: list[AnalysisRelationship] = []
    recommendations: list[RecommendationRelationship] = []

    if reasoning_list:
        # Filter reasoning to only include analyses for known incidents
        validated_reasoning = []
        for r in reasoning_list:
            r_incident_id = r.get("incident_id")
            if r_incident_id in known_incident_ids:
                validated_reasoning.append(r)
            else:
                _logger.warning(
                    "Skipping reasoning '%s': references unknown incident '%s'",
                    r.get("reasoning_id", "?"),
                    r_incident_id,
                )

        if validated_reasoning:
            root_causes, mitigations_list, analyses, recommendations = map_all_reasoning(
                validated_reasoning
            )

    outcomes: list[OutcomeRecord] = []

    return MissionProjection(
        mission=mission,
        incidents=incidents,
        root_causes=root_causes,
        mitigations=mitigations_list,
        analyses=analyses,
        recommendations=recommendations,
        outcomes=outcomes,
        mission_outcome=mission_outcome,
    )


# =============================================================================
# Internal Helpers
# =============================================================================

def _require_fields(data: dict[str, Any], fields: list[str]) -> None:
    """Validate that required fields are present in a dict."""
    missing = [f for f in fields if f not in data or data[f] is None]
    if missing:
        raise ValueError(f"Missing required fields: {', '.join(missing)}")


def _parse_datetime(value: Any) -> datetime:
    """Parse a datetime value from various formats."""
    if value is None:
        raise ValueError("Cannot parse None as datetime")
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        # Handle ISO format with or without timezone
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return dt
        except ValueError:
            pass
        # Try common formats
        for fmt in [
            "%Y-%m-%dT%H:%M:%S.%f",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d %H:%M:%S.%f",
            "%Y-%m-%d %H:%M:%S",
        ]:
            try:
                return datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
    raise ValueError(f"Cannot parse datetime from: {value!r}")


def _mission_result_to_outcome_status(mission_result: str) -> str:
    """
    Map a Phase 2 mission result string to a controlled outcome status.

    This is a bounded mapping; unknown results map to 'unknown'.
    """
    result_lower = mission_result.lower().strip()
    mapping = {
        "success": "recovered",
        "completed": "recovered",
        "nominal": "recovered",
        "partial": "degraded",
        "degraded": "degraded",
        "failed": "failed",
        "failure": "failed",
        "aborted": "failed",
        "crash": "failed",
    }
    return mapping.get(result_lower, "unknown")
