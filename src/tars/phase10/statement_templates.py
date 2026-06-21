"""
Phase 10 Statement Templates
===============================
Deterministic template-based generation of candidate statements.

Statements use cautious association language:
- "is associated with"
- "appears repeatedly with"
- "was observed alongside"

Statements avoid causal language:
- NOT "causes", "fixes", "guarantees", "proves"

All statements are bounded and deterministic for the same input.
"""

from __future__ import annotations

from .models import CandidateType
from .pattern_miner import PatternGroup


def generate_statement(pattern: PatternGroup) -> str:
    """
    Generate a deterministic candidate statement from a pattern group.

    Returns a bounded, cautious statement.
    """
    generators = {
        CandidateType.MITIGATION_EFFECTIVENESS: _mitigation_effectiveness_statement,
        CandidateType.ROOT_CAUSE_PATTERN: _root_cause_pattern_statement,
        CandidateType.REASONING_QUALITY_PATTERN: _reasoning_quality_statement,
        CandidateType.FALSE_POSITIVE_PATTERN: _false_positive_statement,
        CandidateType.FALSE_NEGATIVE_PATTERN: _false_negative_statement,
        CandidateType.RISK_CONTEXT_PATTERN: _risk_context_statement,
    }

    generator = generators.get(pattern.candidate_type)
    if generator is None:
        return (
            f"A {pattern.candidate_type.value} pattern was observed "
            f"with {pattern.support_count} supporting cases "
            f"across {pattern.distinct_mission_count} missions."
        )

    return generator(pattern)


def _mitigation_effectiveness_statement(pattern: PatternGroup) -> str:
    """Generate statement for mitigation effectiveness candidates."""
    mitigation = _humanize(pattern.mitigation or "unknown_mitigation")
    root_cause = _humanize(pattern.root_cause or "unknown_root_cause")
    incident_family = _humanize(pattern.incident_family or "unknown_incident")
    outcome = _humanize(pattern.outcome_family or "positive_outcome")
    rate = f"{pattern.success_rate:.0%}"

    return (
        f"{mitigation} is associated with {outcome} outcomes "
        f"for {root_cause} {incident_family} incidents "
        f"in {rate} of {pattern.total_count} evaluated cases "
        f"across {pattern.distinct_mission_count} distinct missions."
    )


def _root_cause_pattern_statement(pattern: PatternGroup) -> str:
    """Generate statement for root-cause pattern candidates."""
    root_cause = _humanize(pattern.root_cause or "unknown_root_cause")
    incident_family = _humanize(pattern.incident_family or "unknown_incident")
    rate = f"{pattern.success_rate:.0%}"

    return (
        f"{root_cause} appears repeatedly as the accepted root cause "
        f"for {incident_family} incidents, observed in {rate} of "
        f"{pattern.total_count} evaluated cases across "
        f"{pattern.distinct_mission_count} distinct missions."
    )


def _reasoning_quality_statement(pattern: PatternGroup) -> str:
    """Generate statement for reasoning quality pattern candidates."""
    incident_family = _humanize(pattern.incident_family or "unknown_incident")
    metric_name = _humanize(pattern.metric_name or "unknown_metric")
    rate = f"{pattern.success_rate:.0%}"

    return (
        f"Reasoning quality for {metric_name} was observed alongside "
        f"repeated low scores for {incident_family} incidents "
        f"in {rate} of {pattern.total_count} evaluated cases "
        f"across {pattern.distinct_mission_count} distinct missions."
    )


def _false_positive_statement(pattern: PatternGroup) -> str:
    """Generate statement for false-positive pattern candidates."""
    root_cause = _humanize(pattern.root_cause or "unknown_root_cause")
    incident_family = _humanize(pattern.incident_family or "unknown_incident")

    return (
        f"False positive detections were repeatedly observed for "
        f"{root_cause} in {incident_family} incidents, appearing in "
        f"{pattern.support_count} of {pattern.total_count} evaluated cases "
        f"across {pattern.distinct_mission_count} distinct missions."
    )


def _false_negative_statement(pattern: PatternGroup) -> str:
    """Generate statement for false-negative pattern candidates."""
    root_cause = _humanize(pattern.root_cause or "unknown_root_cause")
    incident_family = _humanize(pattern.incident_family or "unknown_incident")

    return (
        f"Missed detections were repeatedly observed for "
        f"{root_cause} in {incident_family} incidents, appearing in "
        f"{pattern.support_count} of {pattern.total_count} evaluated cases "
        f"across {pattern.distinct_mission_count} distinct missions."
    )


def _risk_context_statement(pattern: PatternGroup) -> str:
    """Generate statement for risk context pattern candidates."""
    incident_family = _humanize(pattern.incident_family or "unknown_incident")
    outcome = _humanize(pattern.outcome_family or "negative_outcome")

    return (
        f"{incident_family} incidents were repeatedly associated with "
        f"{outcome} outcomes in {pattern.support_count} of "
        f"{pattern.total_count} evaluated cases across "
        f"{pattern.distinct_mission_count} distinct missions."
    )


def _humanize(snake_case: str) -> str:
    """Convert snake_case to human-readable form."""
    return snake_case.replace("_", " ")
