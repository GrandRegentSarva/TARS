"""
Incident Detector (Collapser)
==============================
Converts matched state sequences into bounded incidents.

The detector:
1. Evaluates all states against deterministic rules.
2. Groups consecutive matches of the same incident type.
3. Merges matches when the gap is below INCIDENT_MAX_GAP_MS.
4. Enforces minimum persistence thresholds (INCIDENT_MIN_STATES).
5. Produces stable incident IDs for deterministic repeated processing.
6. Preserves peak severity, peak risk, phases, and deduplicated evidence.

Immediate rules (sensor_health_failure, high_risk >= 0.8) bypass
the minimum persistence threshold.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict

from .config import settings
from .models import Incident, IncidentType, RuleMatch, Severity
from .rules import evaluate_state


# Incident types that trigger immediately (min_states = 1)
_IMMEDIATE_TYPES = {
    IncidentType.SENSOR_HEALTH_FAILURE,
}

# Severity ordering for comparison
_SEVERITY_ORDER = {
    Severity.LOW: 0,
    Severity.MEDIUM: 1,
    Severity.HIGH: 2,
    Severity.CRITICAL: 3,
}


def _max_severity(a: Severity, b: Severity) -> Severity:
    """Return the higher severity."""
    return a if _SEVERITY_ORDER[a] >= _SEVERITY_ORDER[b] else b


def _generate_incident_id(
    mission_id: str,
    incident_type: str,
    start_sequence: int,
) -> str:
    """
    Generate a stable, deterministic incident ID.

    Based on mission_id + incident_type + start_sequence so that
    repeated processing of the same data produces the same IDs.
    """
    raw = f"{mission_id}:{incident_type}:{start_sequence}"
    digest = hashlib.sha256(raw.encode()).hexdigest()[:16]
    return f"inc_{digest}"


def _is_immediate(match: RuleMatch) -> bool:
    """Check if a match should bypass persistence threshold."""
    if match.incident_type in _IMMEDIATE_TYPES:
        return True
    # High-risk at critical severity (risk >= 0.8) is also immediate
    if (
        match.incident_type == IncidentType.HIGH_RISK_STATE
        and match.severity == Severity.CRITICAL
    ):
        return True
    return False


def detect_incidents(
    states: list[dict],
    mission_id: str,
    max_gap_ms: int | None = None,
    min_states: int | None = None,
) -> list[Incident]:
    """
    Run rule evaluation and collapse matches into bounded incidents.

    Args:
        states: Ordered list of state dicts (Phase 3 StateSnapshot format).
        mission_id: Mission identifier.
        max_gap_ms: Maximum gap between matches to merge (default from config).
        min_states: Minimum states for persistence (default from config).

    Returns:
        List of Incident objects, ordered by start_ms.
    """
    if max_gap_ms is None:
        max_gap_ms = settings.INCIDENT_MAX_GAP_MS
    if min_states is None:
        min_states = settings.INCIDENT_MIN_STATES

    # Step 1: Evaluate all states and group matches by incident type
    matches_by_type: dict[IncidentType, list[RuleMatch]] = defaultdict(list)

    for state in states:
        state_matches = evaluate_state(state)
        for match in state_matches:
            matches_by_type[match.incident_type].append(match)

    # Step 2: Collapse each type's matches into incidents
    incidents: list[Incident] = []

    for incident_type, matches in matches_by_type.items():
        # Sort by sequence to ensure deterministic ordering
        matches.sort(key=lambda m: m.sequence)

        # Group into runs based on gap threshold
        runs = _group_into_runs(matches, max_gap_ms)

        # Apply persistence threshold and create incidents
        effective_min = 1 if _any_immediate(matches) else min_states
        # For battery unstable, min_states = 1
        if incident_type == IncidentType.BATTERY_DEGRADATION:
            for m in matches:
                if m.severity in (Severity.HIGH, Severity.CRITICAL):
                    effective_min = 1
                    break

        for run in runs:
            run_min = effective_min
            # Check if any match in this run is immediate
            for m in run:
                if _is_immediate(m):
                    run_min = 1
                    break

            if len(run) >= run_min:
                incident = _collapse_run(run, mission_id, incident_type)
                incidents.append(incident)

    # Sort by start_ms for deterministic output
    incidents.sort(key=lambda inc: (inc.start_ms, inc.incident_type.value))
    return incidents


def _any_immediate(matches: list[RuleMatch]) -> bool:
    """Check if any match in the list is immediate."""
    return any(_is_immediate(m) for m in matches)


def _group_into_runs(
    matches: list[RuleMatch],
    max_gap_ms: int,
) -> list[list[RuleMatch]]:
    """
    Group sorted matches into runs based on gap threshold.

    Two consecutive matches are in the same run if the gap between
    their elapsed_ms values is <= max_gap_ms.
    """
    if not matches:
        return []

    runs: list[list[RuleMatch]] = [[matches[0]]]

    for match in matches[1:]:
        prev = runs[-1][-1]
        gap = match.elapsed_ms - prev.elapsed_ms
        if gap <= max_gap_ms:
            runs[-1].append(match)
        else:
            runs.append([match])

    return runs


def _collapse_run(
    run: list[RuleMatch],
    mission_id: str,
    incident_type: IncidentType,
) -> Incident:
    """
    Collapse a run of matches into a single bounded incident.

    Preserves:
    - Peak severity
    - Peak risk
    - All unique phases
    - Deduplicated evidence
    """
    first = run[0]
    last = run[-1]

    # Peak severity
    severity = run[0].severity
    for m in run[1:]:
        severity = _max_severity(severity, m.severity)

    # Peak risk
    peak_risk = max(m.risk for m in run)

    # Unique phases (ordered by first appearance)
    seen_phases: set[str] = set()
    phases: list[str] = []
    for m in run:
        if m.phase not in seen_phases:
            seen_phases.add(m.phase)
            phases.append(m.phase)

    # Deduplicated evidence (ordered by first appearance)
    seen_evidence: set[str] = set()
    evidence: list[str] = []
    for m in run:
        for e in m.evidence:
            if e not in seen_evidence:
                seen_evidence.add(e)
                evidence.append(e)

    incident_id = _generate_incident_id(
        mission_id, incident_type.value, first.sequence
    )

    return Incident(
        incident_id=incident_id,
        mission_id=mission_id,
        incident_type=incident_type,
        severity=severity,
        start_sequence=first.sequence,
        end_sequence=last.sequence,
        start_ms=first.elapsed_ms,
        end_ms=last.elapsed_ms,
        contributing_states=len(run),
        peak_risk=min(peak_risk, 1.0),
        phases=phases,
        evidence=evidence,
    )
