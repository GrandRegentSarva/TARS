"""
Phase 10 Evidence Loader
=========================
Merges Phase 9 evaluation summaries with Phase 7 operational context
and optional Phoenix trace metadata into bounded LearningEvidence records.

Responsibilities:
- Normalize root causes, mitigations, outcomes, and incident families.
- Deduplicate evidence by evaluation ID.
- Emit bounded evidence records with identifiers only.
- Lower evidence strength when optional context is missing.

Evidence records contain identifiers and bounded metadata only.
Missing optional context lowers evidence strength instead of inventing facts.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Optional

from .models import EvidenceLevel, LearningEvidence

logger = logging.getLogger("phase10.evidence_loader")

# Outcomes considered successful for mitigation effectiveness
_POSITIVE_OUTCOMES = {"recovered", "stabilized", "mitigated", "nominal"}

# Outcomes considered negative
_NEGATIVE_OUTCOMES = {"failed", "crashed", "degraded", "lost"}


def normalize_string(value: Optional[str]) -> Optional[str]:
    """Normalize a string value for grouping."""
    if value is None:
        return None
    return value.strip().lower().replace(" ", "_").replace("-", "_")


def _infer_incident_family(incident_id: Optional[str]) -> Optional[str]:
    """
    Infer incident family from incident ID prefix.

    Uses the first underscore-delimited segment, e.g.
    ``nav_inc_001`` → ``nav``, ``battery_drain_002`` → ``battery``.
    Returns ``None`` when no incident ID is available.
    """
    if not incident_id:
        return None
    parts = incident_id.split("_")
    return parts[0].lower() if parts else None


class EvidenceLoader:
    """
    Loads and normalizes evidence from Phase 9 evaluations,
    Phase 7 operational memory, and optional Phoenix trace metadata.
    """

    def __init__(
        self,
        phase9_client: Any = None,
        phase7_client: Any = None,
        phoenix_client: Any = None,
    ) -> None:
        self._phase9 = phase9_client
        self._phase7 = phase7_client
        self._phoenix = phoenix_client

    async def load_evidence(
        self,
        mission_ids: Optional[list[str]] = None,
        incident_family: Optional[str] = None,
        root_cause: Optional[str] = None,
        since: Optional[str] = None,
        until: Optional[str] = None,
        limit: int = 100,
    ) -> tuple[list[LearningEvidence], list[str]]:
        """
        Load bounded evidence from upstream sources.

        Returns:
            (evidence_items, warnings) where warnings are non-fatal issues.
        """
        warnings: list[str] = []
        evidence_items: list[LearningEvidence] = []
        seen_evaluation_ids: set[str] = set()

        # 1. Load Phase 9 evaluations
        evaluations = await self._load_evaluations(
            mission_ids=mission_ids,
            since=since,
            until=until,
            limit=limit,
        )

        if not evaluations:
            warnings.append("No evaluations found for the given filters.")
            return evidence_items, warnings

        # 2. For each evaluation, build evidence
        for eval_data in evaluations:
            eval_id = eval_data.get("evaluation_id", "")

            # Deduplicate by evaluation ID
            if eval_id in seen_evaluation_ids:
                continue
            seen_evaluation_ids.add(eval_id)

            evidence = await self._build_evidence_from_evaluation(
                eval_data, warnings
            )

            if evidence is None:
                continue

            # Apply filters
            if incident_family:
                inferred = _infer_incident_family(evidence.incident_id)
                if inferred != normalize_string(incident_family):
                    continue

            if root_cause and evidence.root_cause != normalize_string(root_cause):
                continue

            evidence_items.append(evidence)

            if len(evidence_items) >= limit:
                break

        logger.info(
            "Loaded %d evidence items from %d evaluations",
            len(evidence_items),
            len(evaluations),
        )

        return evidence_items, warnings

    async def _load_evaluations(
        self,
        mission_ids: Optional[list[str]],
        since: Optional[str],
        until: Optional[str],
        limit: int,
    ) -> list[dict[str, Any]]:
        """Load evaluations from Phase 9."""
        if self._phase9 is None:
            return []

        try:
            return await self._phase9.list_all_evaluations(
                mission_ids=mission_ids,
                since=since,
                until=until,
                limit=limit,
            )
        except Exception as exc:
            logger.error("Failed to load evaluations from Phase 9: %s", exc)
            raise

    async def _build_evidence_from_evaluation(
        self,
        eval_data: dict[str, Any],
        warnings: list[str],
    ) -> Optional[LearningEvidence]:
        """
        Build a LearningEvidence record from an evaluation dict.

        Enriches with Phase 7 context and Phoenix metadata when available.
        """
        eval_id = eval_data.get("evaluation_id", "")
        mission_id = eval_data.get("mission_id", "")
        incident_id = eval_data.get("incident_id")
        reasoning_id = eval_data.get("reasoning_id")
        trace_id = eval_data.get("trace_id")
        overall_score = eval_data.get("overall_score")

        if not mission_id:
            return None

        # Extract metric labels from evaluation metrics
        metric_labels = self._extract_metric_labels(eval_data)

        # Determine evidence levels
        evidence_levels = self._determine_evidence_levels(eval_data)

        # Extract root cause and mitigation from evaluation context
        root_cause = None
        mitigation = None
        outcome = None

        # Try to get context from Phase 7
        if self._phase7 and incident_id:
            try:
                memory = await self._phase7.get_incident_memory(incident_id)
                if memory:
                    root_cause = self._extract_root_cause(memory)
                    mitigation = self._extract_mitigation(memory)
                    outcome = self._extract_outcome(memory)
                    if EvidenceLevel.OPERATIONAL_MEMORY.value not in evidence_levels:
                        evidence_levels.append(
                            EvidenceLevel.OPERATIONAL_MEMORY.value
                        )
            except Exception as exc:
                warnings.append(
                    f"Phase 7 context unavailable for incident "
                    f"'{incident_id}': {str(exc)[:100]}"
                )

        # Try mission-level outcomes from Phase 7
        if self._phase7 and not outcome:
            try:
                mission_data = await self._phase7.get_mission_outcomes(
                    mission_id
                )
                if mission_data:
                    outcome = self._extract_outcome(mission_data)
            except Exception as exc:
                warnings.append(
                    f"Phase 7 mission outcomes unavailable for "
                    f"'{mission_id}': {str(exc)[:100]}"
                )

        # Attach Phoenix trace metadata (IDs only)
        if self._phoenix and trace_id:
            try:
                trace_meta = await self._phoenix.get_trace_metadata(trace_id)
                if trace_meta and EvidenceLevel.TRACE_METADATA.value not in evidence_levels:
                    evidence_levels.append(
                        EvidenceLevel.TRACE_METADATA.value
                    )
            except Exception as exc:
                warnings.append(
                    f"Phoenix metadata unavailable for trace "
                    f"'{trace_id}': {str(exc)[:100]}"
                )

        evidence_id = f"ev_{uuid.uuid4().hex[:16]}"

        return LearningEvidence(
            evidence_id=evidence_id,
            mission_id=mission_id,
            incident_id=incident_id,
            reasoning_id=reasoning_id,
            evaluation_id=eval_id,
            trace_id=trace_id,
            root_cause=root_cause,
            mitigation=mitigation,
            outcome=outcome,
            overall_score=overall_score,
            metric_labels=metric_labels,
            evidence_levels=evidence_levels,
        )

    def _extract_metric_labels(
        self,
        eval_data: dict[str, Any],
    ) -> dict[str, str]:
        """Extract metric classification labels from evaluation data."""
        labels: dict[str, str] = {}
        metrics = eval_data.get("metrics", [])

        for metric in metrics:
            if isinstance(metric, dict):
                name = metric.get("name", "")
                label = metric.get("label", "")
                if name and label:
                    labels[name] = label

        # Also check for false positive/negative flags
        if eval_data.get("false_positive"):
            labels["false_positive"] = "true"
        if eval_data.get("false_negative"):
            labels["false_negative"] = "true"

        return labels

    # ------------------------------------------------------------------
    # Phase 7 field extraction helpers
    # ------------------------------------------------------------------
    # Phase 7 IncidentMemoryResponse returns lists:
    #   root_causes: [{classification, ...}]
    #   recommended_mitigations / applied_mitigations: [{description, ...}]
    #   outcomes: [{status, ...}]
    # Flat keys (root_cause, mitigation, outcome) are also accepted for
    # test fakes and forward compatibility.

    def _extract_root_cause(self, memory: dict[str, Any]) -> Optional[str]:
        """Extract first root cause from Phase 7 incident memory."""
        # Try list form first (real API shape)
        root_causes = memory.get("root_causes", [])
        if root_causes and isinstance(root_causes, list):
            first = root_causes[0]
            if isinstance(first, dict):
                return normalize_string(
                    first.get("classification")
                    or first.get("normalized_classification")
                )
            return normalize_string(str(first))
        # Fall back to flat key (test fakes)
        return normalize_string(
            memory.get("root_cause")
            or memory.get("accepted_root_cause")
        )

    def _extract_mitigation(self, memory: dict[str, Any]) -> Optional[str]:
        """Extract first mitigation from Phase 7 incident memory."""
        # Try applied_mitigations first (strongest evidence)
        for key in ("applied_mitigations", "recommended_mitigations"):
            mits = memory.get(key, [])
            if mits and isinstance(mits, list):
                first = mits[0]
                if isinstance(first, dict):
                    return normalize_string(first.get("description"))
                return normalize_string(str(first))
        # Fall back to flat key (test fakes)
        return normalize_string(
            memory.get("mitigation")
            or memory.get("applied_mitigation")
        )

    def _extract_outcome(self, memory: dict[str, Any]) -> Optional[str]:
        """Extract first outcome from Phase 7 incident/mission memory."""
        outcomes = memory.get("outcomes", [])
        if outcomes and isinstance(outcomes, list):
            first = outcomes[0]
            if isinstance(first, dict):
                return normalize_string(
                    first.get("status") or first.get("description")
                )
            return normalize_string(str(first))
        # Fall back to flat key (test fakes)
        return normalize_string(
            memory.get("outcome")
            or memory.get("mission_outcome")
            or memory.get("resolution")
        )

    def _determine_evidence_levels(
        self,
        eval_data: dict[str, Any],
    ) -> list[str]:
        """Determine evidence strength levels from evaluation data."""
        levels: list[str] = []

        evidence_level = eval_data.get("evidence_level", "")

        if evidence_level == "operator_label":
            levels.append(EvidenceLevel.OPERATOR_LABEL.value)
        elif evidence_level == "mission_outcome":
            levels.append(EvidenceLevel.MISSION_OUTCOME.value)
        elif evidence_level == "deterministic_incident":
            levels.append(EvidenceLevel.DETERMINISTIC_INCIDENT.value)

        # Evaluation metrics are always present if we have an evaluation
        if eval_data.get("overall_score") is not None:
            levels.append(EvidenceLevel.EVALUATION_METRIC.value)

        return levels


def is_positive_outcome(outcome: Optional[str]) -> bool:
    """Check if an outcome is considered positive."""
    if outcome is None:
        return False
    return normalize_string(outcome) in _POSITIVE_OUTCOMES


def is_negative_outcome(outcome: Optional[str]) -> bool:
    """Check if an outcome is considered negative."""
    if outcome is None:
        return False
    return normalize_string(outcome) in _NEGATIVE_OUTCOMES
