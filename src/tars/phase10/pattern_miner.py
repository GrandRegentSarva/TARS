"""
Phase 10 Pattern Miner
========================
Deterministic grouping of evaluated evidence into candidate patterns.

Implements pattern mining for:
- Mitigation effectiveness
- Root-cause patterns
- Reasoning quality patterns
- False-positive patterns
- False-negative patterns
- Risk context patterns

Patterns below support thresholds are suppressed with reasons.
Contradictions are counted separately from support.
Pattern outputs are deterministic for the same evidence input.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional

from .config import settings
from .evidence_loader import is_negative_outcome, is_positive_outcome, normalize_string
from .models import CandidateType, LearningEvidence

logger = logging.getLogger("phase10.pattern_miner")


@dataclass
class PatternGroup:
    """A group of evidence items forming a candidate pattern."""
    candidate_type: CandidateType
    group_key: str
    incident_family: Optional[str] = None
    root_cause: Optional[str] = None
    mitigation: Optional[str] = None
    outcome_family: Optional[str] = None
    model: Optional[str] = None
    prompt_version: Optional[str] = None
    metric_name: Optional[str] = None
    support_items: list[LearningEvidence] = field(default_factory=list)
    contradiction_items: list[LearningEvidence] = field(default_factory=list)
    all_items: list[LearningEvidence] = field(default_factory=list)

    @property
    def support_count(self) -> int:
        return len(self.support_items)

    @property
    def contradiction_count(self) -> int:
        return len(self.contradiction_items)

    @property
    def total_count(self) -> int:
        return len(self.all_items)

    @property
    def distinct_missions(self) -> set[str]:
        return {e.mission_id for e in self.all_items}

    @property
    def distinct_mission_count(self) -> int:
        return len(self.distinct_missions)

    @property
    def success_rate(self) -> float:
        if self.total_count == 0:
            return 0.0
        return self.support_count / self.total_count

    @property
    def mean_overall_score(self) -> Optional[float]:
        scores = [
            e.overall_score for e in self.all_items
            if e.overall_score is not None
        ]
        if not scores:
            return None
        return sum(scores) / len(scores)


@dataclass
class SuppressionReason:
    """Reason a pattern was suppressed."""
    group_key: str
    candidate_type: CandidateType
    reason: str


class PatternMiner:
    """
    Deterministic pattern miner for learning evidence.

    Groups evidence into candidate patterns and identifies
    support and contradiction items.
    """

    def __init__(
        self,
        min_evaluated_cases: Optional[int] = None,
        min_distinct_missions: Optional[int] = None,
        min_success_rate: Optional[float] = None,
        max_false_positive_rate: Optional[float] = None,
    ) -> None:
        self._min_cases = (
            min_evaluated_cases
            or settings.LEARNING_MIN_EVALUATED_CASES
        )
        self._min_missions = (
            min_distinct_missions
            or settings.LEARNING_MIN_DISTINCT_MISSIONS
        )
        self._min_success_rate = (
            min_success_rate
            if min_success_rate is not None
            else settings.LEARNING_MIN_SUCCESS_RATE
        )
        self._max_fp_rate = (
            max_false_positive_rate
            if max_false_positive_rate is not None
            else settings.LEARNING_MAX_FALSE_POSITIVE_RATE
        )

    def mine_patterns(
        self,
        evidence: list[LearningEvidence],
        candidate_types: Optional[list[CandidateType]] = None,
    ) -> tuple[list[PatternGroup], list[SuppressionReason]]:
        """
        Mine patterns from evidence items.

        Returns:
            (accepted_patterns, suppression_reasons)
        """
        if candidate_types is None:
            candidate_types = list(CandidateType)

        all_patterns: list[PatternGroup] = []
        all_suppressions: list[SuppressionReason] = []

        miners = {
            CandidateType.MITIGATION_EFFECTIVENESS: self._mine_mitigation_effectiveness,
            CandidateType.ROOT_CAUSE_PATTERN: self._mine_root_cause_patterns,
            CandidateType.REASONING_QUALITY_PATTERN: self._mine_reasoning_quality,
            CandidateType.FALSE_POSITIVE_PATTERN: self._mine_false_positive,
            CandidateType.FALSE_NEGATIVE_PATTERN: self._mine_false_negative,
            CandidateType.RISK_CONTEXT_PATTERN: self._mine_risk_context,
        }

        for ct in candidate_types:
            miner_fn = miners.get(ct)
            if miner_fn is None:
                continue

            patterns, suppressions = miner_fn(evidence)
            all_patterns.extend(patterns)
            all_suppressions.extend(suppressions)

        logger.info(
            "Mined %d patterns, suppressed %d from %d evidence items",
            len(all_patterns),
            len(all_suppressions),
            len(evidence),
        )

        return all_patterns, all_suppressions

    # -----------------------------------------------------------------------
    # Mitigation Effectiveness
    # -----------------------------------------------------------------------

    def _mine_mitigation_effectiveness(
        self,
        evidence: list[LearningEvidence],
    ) -> tuple[list[PatternGroup], list[SuppressionReason]]:
        """
        Group by incident_family + root_cause + mitigation.

        Support: positive outcome + correct/partially_correct recommendation.
        Contradiction: negative outcome + incorrect recommendation.
        """
        groups: dict[str, PatternGroup] = {}

        for ev in evidence:
            if not ev.root_cause or not ev.mitigation:
                continue

            # Infer incident family from context
            incident_family = self._infer_incident_family(ev)
            key = f"{incident_family}:{ev.root_cause}:{ev.mitigation}"

            if key not in groups:
                groups[key] = PatternGroup(
                    candidate_type=CandidateType.MITIGATION_EFFECTIVENESS,
                    group_key=key,
                    incident_family=incident_family,
                    root_cause=ev.root_cause,
                    mitigation=ev.mitigation,
                )

            group = groups[key]
            group.all_items.append(ev)

            # Classify as support or contradiction
            rec_label = ev.metric_labels.get("recommendation_accuracy", "")
            is_support = (
                is_positive_outcome(ev.outcome)
                and rec_label in ("correct", "partially_correct")
            )
            is_contradiction = (
                is_negative_outcome(ev.outcome)
                or rec_label == "incorrect"
            )

            if is_support:
                group.support_items.append(ev)
                if is_positive_outcome(ev.outcome):
                    group.outcome_family = "recovered_or_stabilized"
            elif is_contradiction:
                group.contradiction_items.append(ev)

        return self._filter_patterns(groups)

    # -----------------------------------------------------------------------
    # Root-Cause Pattern
    # -----------------------------------------------------------------------

    def _mine_root_cause_patterns(
        self,
        evidence: list[LearningEvidence],
    ) -> tuple[list[PatternGroup], list[SuppressionReason]]:
        """
        Group by incident_family + accepted_root_cause.

        Support: root_cause_accuracy is correct or partially_correct.
        """
        groups: dict[str, PatternGroup] = {}

        for ev in evidence:
            if not ev.root_cause:
                continue

            incident_family = self._infer_incident_family(ev)
            key = f"{incident_family}:{ev.root_cause}"

            if key not in groups:
                groups[key] = PatternGroup(
                    candidate_type=CandidateType.ROOT_CAUSE_PATTERN,
                    group_key=key,
                    incident_family=incident_family,
                    root_cause=ev.root_cause,
                )

            group = groups[key]
            group.all_items.append(ev)

            rc_label = ev.metric_labels.get("root_cause_accuracy", "")
            if rc_label in ("correct", "partially_correct"):
                group.support_items.append(ev)
            elif rc_label == "incorrect":
                group.contradiction_items.append(ev)

        return self._filter_patterns(groups)

    # -----------------------------------------------------------------------
    # Reasoning Quality Pattern
    # -----------------------------------------------------------------------

    def _mine_reasoning_quality(
        self,
        evidence: list[LearningEvidence],
    ) -> tuple[list[PatternGroup], list[SuppressionReason]]:
        """
        Group by model + prompt_version + incident_family + metric_name.

        Support: repeated low or high metric labels for a configuration.
        """
        groups: dict[str, PatternGroup] = {}

        for ev in evidence:
            incident_family = self._infer_incident_family(ev)

            for metric_name, label in ev.metric_labels.items():
                if metric_name in ("false_positive", "false_negative"):
                    continue  # Handled by separate miners

                # We don't have model/prompt_version in evidence directly,
                # so group by incident_family + metric_name
                key = f"{incident_family}:{metric_name}:{label}"

                if key not in groups:
                    groups[key] = PatternGroup(
                        candidate_type=CandidateType.REASONING_QUALITY_PATTERN,
                        group_key=key,
                        incident_family=incident_family,
                        metric_name=metric_name,
                    )

                group = groups[key]
                group.all_items.append(ev)

                # Low quality is support for a "quality problem" pattern
                if label in ("incorrect", "insufficient_evidence"):
                    group.support_items.append(ev)
                elif label in ("correct",):
                    group.contradiction_items.append(ev)

        return self._filter_patterns(groups)

    # -----------------------------------------------------------------------
    # False-Positive Pattern
    # -----------------------------------------------------------------------

    def _mine_false_positive(
        self,
        evidence: list[LearningEvidence],
    ) -> tuple[list[PatternGroup], list[SuppressionReason]]:
        """
        Group by incident_family + predicted_root_cause for false positives.

        Support: repeated Phase 9 false-positive labels.
        """
        groups: dict[str, PatternGroup] = {}

        for ev in evidence:
            if ev.metric_labels.get("false_positive") != "true":
                continue

            incident_family = self._infer_incident_family(ev)
            root_cause = ev.root_cause or "unknown"
            key = f"{incident_family}:{root_cause}:fp"

            if key not in groups:
                groups[key] = PatternGroup(
                    candidate_type=CandidateType.FALSE_POSITIVE_PATTERN,
                    group_key=key,
                    incident_family=incident_family,
                    root_cause=root_cause,
                )

            group = groups[key]
            group.all_items.append(ev)
            group.support_items.append(ev)

        return self._filter_patterns(groups)

    # -----------------------------------------------------------------------
    # False-Negative Pattern
    # -----------------------------------------------------------------------

    def _mine_false_negative(
        self,
        evidence: list[LearningEvidence],
    ) -> tuple[list[PatternGroup], list[SuppressionReason]]:
        """
        Group by incident_family + missed root cause for false negatives.

        Support: repeated Phase 9 false-negative labels.
        """
        groups: dict[str, PatternGroup] = {}

        for ev in evidence:
            if ev.metric_labels.get("false_negative") != "true":
                continue

            incident_family = self._infer_incident_family(ev)
            root_cause = ev.root_cause or "unknown"
            key = f"{incident_family}:{root_cause}:fn"

            if key not in groups:
                groups[key] = PatternGroup(
                    candidate_type=CandidateType.FALSE_NEGATIVE_PATTERN,
                    group_key=key,
                    incident_family=incident_family,
                    root_cause=root_cause,
                )

            group = groups[key]
            group.all_items.append(ev)
            group.support_items.append(ev)

        return self._filter_patterns(groups)

    # -----------------------------------------------------------------------
    # Risk Context Pattern
    # -----------------------------------------------------------------------

    def _mine_risk_context(
        self,
        evidence: list[LearningEvidence],
    ) -> tuple[list[PatternGroup], list[SuppressionReason]]:
        """
        Group by incident_family + outcome for risk context patterns.

        Support: repeated negative outcomes for an incident family.
        """
        groups: dict[str, PatternGroup] = {}

        for ev in evidence:
            if not ev.outcome:
                continue

            incident_family = self._infer_incident_family(ev)
            outcome = normalize_string(ev.outcome) or "unknown"
            key = f"{incident_family}:{outcome}:risk"

            if key not in groups:
                groups[key] = PatternGroup(
                    candidate_type=CandidateType.RISK_CONTEXT_PATTERN,
                    group_key=key,
                    incident_family=incident_family,
                    outcome_family=outcome,
                )

            group = groups[key]
            group.all_items.append(ev)

            if is_negative_outcome(ev.outcome):
                group.support_items.append(ev)
            elif is_positive_outcome(ev.outcome):
                group.contradiction_items.append(ev)

        return self._filter_patterns(groups)

    # -----------------------------------------------------------------------
    # Filtering
    # -----------------------------------------------------------------------

    def _filter_patterns(
        self,
        groups: dict[str, PatternGroup],
    ) -> tuple[list[PatternGroup], list[SuppressionReason]]:
        """
        Filter patterns by minimum thresholds.

        Returns (accepted, suppressed).
        """
        accepted: list[PatternGroup] = []
        suppressed: list[SuppressionReason] = []

        for key, group in groups.items():
            # Check minimum evaluated cases
            if group.total_count < self._min_cases:
                suppressed.append(SuppressionReason(
                    group_key=key,
                    candidate_type=group.candidate_type,
                    reason=(
                        f"Below minimum evaluated cases: "
                        f"{group.total_count} < {self._min_cases}"
                    ),
                ))
                continue

            # Check minimum distinct missions
            if group.distinct_mission_count < self._min_missions:
                suppressed.append(SuppressionReason(
                    group_key=key,
                    candidate_type=group.candidate_type,
                    reason=(
                        f"Below minimum distinct missions: "
                        f"{group.distinct_mission_count} < {self._min_missions}"
                    ),
                ))
                continue

            # For positive mitigation candidates, check success rate
            if group.candidate_type == CandidateType.MITIGATION_EFFECTIVENESS:
                if group.success_rate < self._min_success_rate:
                    suppressed.append(SuppressionReason(
                        group_key=key,
                        candidate_type=group.candidate_type,
                        reason=(
                            f"Below minimum success rate: "
                            f"{group.success_rate:.2f} < {self._min_success_rate}"
                        ),
                    ))
                    continue

                # Check false positive rate
                fp_rate = (
                    group.contradiction_count / group.total_count
                    if group.total_count > 0
                    else 0.0
                )
                if fp_rate > self._max_fp_rate:
                    suppressed.append(SuppressionReason(
                        group_key=key,
                        candidate_type=group.candidate_type,
                        reason=(
                            f"Above maximum false positive rate: "
                            f"{fp_rate:.2f} > {self._max_fp_rate}"
                        ),
                    ))
                    continue

            accepted.append(group)

        return accepted, suppressed

    # -----------------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------------

    def _infer_incident_family(self, ev: LearningEvidence) -> str:
        """
        Infer incident family from evidence.

        Uses incident_id prefix or falls back to 'unknown'.
        """
        if ev.incident_id:
            # Try to extract type from incident ID pattern
            parts = ev.incident_id.split("_")
            if len(parts) >= 2:
                return parts[0]
        return "unknown"
