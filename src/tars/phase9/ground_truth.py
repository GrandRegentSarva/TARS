"""
Ground Truth Loading
=====================
Resolves ground-truth labels for evaluation from multiple sources.

Priority order:
1. Explicit labels in the evaluation request.
2. Stored labels in the evaluation database.
3. Optional outcome-derived labels from Phase 7 (when available).

Returns structured missing-evidence results instead of raising
for normal absence. Missing ground truth is a first-class result.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from .config import settings
from .models import (
    EvidenceLevel,
    GroundTruthLabel,
    GroundTruthPayload,
    GroundTruthSource,
)

logger = logging.getLogger("phase9.ground_truth")


class GroundTruthResult:
    """
    Result of ground-truth resolution.

    Contains the resolved label (if any), the evidence level,
    and whether evidence was sufficient.
    """

    def __init__(
        self,
        label: Optional[GroundTruthLabel] = None,
        evidence_level: Optional[str] = None,
        has_evidence: bool = False,
    ) -> None:
        self.label = label
        self.evidence_level = evidence_level
        self.has_evidence = has_evidence

    @classmethod
    def insufficient(cls) -> GroundTruthResult:
        """Create a result indicating insufficient evidence."""
        return cls(label=None, evidence_level=None, has_evidence=False)


class GroundTruthLoader:
    """
    Resolves ground-truth labels from multiple sources.

    Uses a priority chain:
    1. Explicit request payload.
    2. Stored labels in the evaluation database.
    3. Phase 7 outcome-derived labels (optional).
    """

    def __init__(
        self,
        repository: Any = None,
        phase7_client: Any = None,
    ) -> None:
        self._repository = repository
        self._phase7_client = phase7_client

    async def resolve(
        self,
        mission_id: str,
        incident_id: Optional[str] = None,
        reasoning_id: Optional[str] = None,
        request_ground_truth: Optional[GroundTruthPayload] = None,
    ) -> GroundTruthResult:
        """
        Resolve ground-truth label for an evaluation target.

        Args:
            mission_id: Mission identifier.
            incident_id: Optional incident identifier.
            reasoning_id: Optional reasoning identifier.
            request_ground_truth: Optional inline label from request.

        Returns:
            GroundTruthResult with resolved label or insufficient evidence.
        """
        # 1. Explicit request labels take highest priority
        if request_ground_truth is not None:
            label = self._from_request_payload(request_ground_truth)
            if label is not None:
                return GroundTruthResult(
                    label=label,
                    evidence_level=EvidenceLevel.OPERATOR_LABEL.value,
                    has_evidence=True,
                )

        # 2. Stored labels in the evaluation database
        if self._repository is not None:
            stored = await self._from_stored_labels(mission_id, incident_id)
            if stored is not None:
                return stored

        # 3. Phase 7 outcome-derived labels (optional)
        if (
            self._phase7_client is not None
            and not settings.EVALUATION_REQUIRE_OPERATOR_LABEL
        ):
            derived = await self._from_phase7(mission_id, incident_id)
            if derived is not None:
                return derived

        # No evidence found
        logger.info(
            "No ground truth found for mission='%s' incident='%s'",
            mission_id,
            incident_id,
        )
        return GroundTruthResult.insufficient()

    def _from_request_payload(
        self,
        payload: GroundTruthPayload,
    ) -> Optional[GroundTruthLabel]:
        """Convert an inline request payload to a GroundTruthLabel."""
        if not payload.root_cause and not payload.outcome:
            return None

        return GroundTruthLabel(
            root_cause=payload.root_cause,
            preferred_mitigation=payload.preferred_mitigation,
            outcome=payload.outcome,
            source=GroundTruthSource.OPERATOR_LABEL,
            labeled_by="request",
        )

    async def _from_stored_labels(
        self,
        mission_id: str,
        incident_id: Optional[str],
    ) -> Optional[GroundTruthResult]:
        """Load stored labels from the evaluation database."""
        try:
            labels = await self._repository.get_labels_for_target(
                mission_id=mission_id,
                incident_id=incident_id,
            )
            if not labels:
                return None

            # Use the highest-priority label (already sorted by source)
            best = labels[0]
            label = GroundTruthLabel(
                root_cause=best.root_cause,
                preferred_mitigation=best.preferred_mitigation,
                outcome=best.outcome,
                source=GroundTruthSource(best.source.value),
                labeled_by=best.labeled_by,
                labeled_at=best.labeled_at,
            )

            # Map source to evidence level
            evidence_map = {
                GroundTruthSource.OPERATOR_LABEL: EvidenceLevel.OPERATOR_LABEL,
                GroundTruthSource.MISSION_OUTCOME: EvidenceLevel.MISSION_OUTCOME,
                GroundTruthSource.SYNTHETIC_TEST_CASE: EvidenceLevel.OPERATOR_LABEL,
                GroundTruthSource.DETERMINISTIC_RULE: EvidenceLevel.DETERMINISTIC_INCIDENT,
            }
            evidence_level = evidence_map.get(
                label.source,
                EvidenceLevel.TRACE_METADATA,
            )

            return GroundTruthResult(
                label=label,
                evidence_level=evidence_level.value,
                has_evidence=True,
            )
        except Exception as exc:
            logger.warning("Failed to load stored labels: %s", exc)
            return None

    async def _from_phase7(
        self,
        mission_id: str,
        incident_id: Optional[str],
    ) -> Optional[GroundTruthResult]:
        """Derive labels from Phase 7 outcome data."""
        try:
            if incident_id:
                memory = await self._phase7_client.get_incident_memory(
                    incident_id
                )
                if memory and memory.get("outcomes"):
                    outcomes = memory["outcomes"]
                    # Use the first outcome
                    outcome = outcomes[0]
                    root_causes = memory.get("root_causes", [])
                    applied_mits = memory.get("applied_mitigations", [])

                    label = GroundTruthLabel(
                        root_cause=(
                            root_causes[0].get("classification")
                            if root_causes
                            else None
                        ),
                        preferred_mitigation=(
                            applied_mits[0].get("description")
                            if applied_mits
                            else None
                        ),
                        outcome=outcome.get("status"),
                        source=GroundTruthSource.MISSION_OUTCOME,
                        labeled_by="phase7",
                    )

                    return GroundTruthResult(
                        label=label,
                        evidence_level=EvidenceLevel.MISSION_OUTCOME.value,
                        has_evidence=True,
                    )
            else:
                # Mission-level outcome
                sync_data = await self._phase7_client.get_mission_outcomes(
                    mission_id
                )
                if sync_data and sync_data.get("status") == "complete":
                    return GroundTruthResult(
                        label=GroundTruthLabel(
                            outcome=sync_data.get("status"),
                            source=GroundTruthSource.MISSION_OUTCOME,
                            labeled_by="phase7",
                        ),
                        evidence_level=EvidenceLevel.MISSION_OUTCOME.value,
                        has_evidence=True,
                    )
        except Exception as exc:
            logger.warning("Failed to derive labels from Phase 7: %s", exc)

        return None
