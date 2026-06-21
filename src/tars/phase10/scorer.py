"""
Phase 10 Candidate Scorer
===========================
Computes versioned confidence scores for candidate knowledge.

Confidence scoring formula:

    confidence =
        0.35 * support_strength
      + 0.25 * outcome_strength
      + 0.20 * evaluation_quality
      + 0.10 * evidence_diversity
      + 0.10 * contradiction_penalty_adjusted

All scores are bounded [0.0, 1.0].
Formula changes require a new LEARNING_VERSION.
"""

from __future__ import annotations

import logging
import math
from typing import Optional

from .config import settings
from .models import CandidateType, EvidenceLevel
from .pattern_miner import PatternGroup

logger = logging.getLogger("phase10.scorer")

# Maximum counts for normalization
_MAX_SUPPORT_COUNT = 50
_MAX_MISSION_COUNT = 20


class CandidateScorer:
    """
    Versioned confidence scorer for candidate knowledge.

    Computes support strength, outcome strength, evaluation quality,
    evidence diversity, and contradiction penalty.
    """

    def __init__(
        self,
        version: Optional[str] = None,
        weights: Optional[dict[str, float]] = None,
    ) -> None:
        self._version = version or settings.LEARNING_VERSION
        self._weights = weights or settings.scoring_weights

    @property
    def version(self) -> str:
        return self._version

    def score(self, pattern: PatternGroup) -> float:
        """
        Compute confidence score for a pattern group.

        Returns a bounded float in [0.0, 1.0].
        """
        support = self._support_strength(pattern)
        outcome = self._outcome_strength(pattern)
        evaluation = self._evaluation_quality(pattern)
        diversity = self._evidence_diversity(pattern)
        contradiction = self._contradiction_penalty_adjusted(pattern)

        confidence = (
            self._weights["support_strength"] * support
            + self._weights["outcome_strength"] * outcome
            + self._weights["evaluation_quality"] * evaluation
            + self._weights["evidence_diversity"] * diversity
            + self._weights["contradiction_penalty_adjusted"] * contradiction
        )

        # Clamp to [0.0, 1.0]
        confidence = max(0.0, min(1.0, confidence))

        logger.debug(
            "Scored pattern '%s': support=%.2f outcome=%.2f "
            "eval=%.2f diversity=%.2f contradiction=%.2f -> %.3f",
            pattern.group_key,
            support,
            outcome,
            evaluation,
            diversity,
            contradiction,
            confidence,
        )

        return round(confidence, 4)

    def _support_strength(self, pattern: PatternGroup) -> float:
        """
        Score based on support count and distinct mission count.

        Uses logarithmic scaling to avoid over-weighting large counts.
        """
        # Normalize support count (log scale, max at _MAX_SUPPORT_COUNT)
        support_norm = min(
            1.0,
            math.log1p(pattern.support_count) / math.log1p(_MAX_SUPPORT_COUNT),
        )

        # Normalize distinct mission count
        mission_norm = min(
            1.0,
            math.log1p(pattern.distinct_mission_count) / math.log1p(_MAX_MISSION_COUNT),
        )

        # Weighted combination
        return 0.6 * support_norm + 0.4 * mission_norm

    def _outcome_strength(self, pattern: PatternGroup) -> float:
        """
        Score based on success rate for positive candidates
        or recurrence rate for failure-pattern candidates.
        """
        if pattern.candidate_type in (
            CandidateType.MITIGATION_EFFECTIVENESS,
            CandidateType.ROOT_CAUSE_PATTERN,
        ):
            return pattern.success_rate
        elif pattern.candidate_type in (
            CandidateType.FALSE_POSITIVE_PATTERN,
            CandidateType.FALSE_NEGATIVE_PATTERN,
        ):
            # For failure patterns, recurrence rate is the signal
            if pattern.total_count == 0:
                return 0.0
            return pattern.support_count / pattern.total_count
        elif pattern.candidate_type == CandidateType.REASONING_QUALITY_PATTERN:
            # For quality patterns, consistency of the quality signal
            if pattern.total_count == 0:
                return 0.0
            return pattern.support_count / pattern.total_count
        else:
            return pattern.success_rate

    def _evaluation_quality(self, pattern: PatternGroup) -> float:
        """
        Score based on mean Phase 9 overall score and metric labels.

        Higher evaluation scores indicate more reliable evidence.
        """
        mean_score = pattern.mean_overall_score
        if mean_score is None:
            return 0.5  # Neutral when no scores available

        return mean_score

    def _evidence_diversity(self, pattern: PatternGroup) -> float:
        """
        Score based on evidence across multiple missions, incidents,
        and evidence sources.

        Rewards evidence from diverse sources.
        """
        # Count distinct evidence levels across all items
        all_levels: set[str] = set()
        distinct_incidents: set[str] = set()

        for ev in pattern.all_items:
            for level in ev.evidence_levels:
                all_levels.add(level)
            if ev.incident_id:
                distinct_incidents.add(ev.incident_id)

        # Normalize: max 6 evidence levels
        level_diversity = min(1.0, len(all_levels) / 4.0)

        # Normalize: distinct incidents relative to total
        incident_diversity = min(
            1.0,
            len(distinct_incidents) / max(1, pattern.total_count),
        )

        # Mission diversity
        mission_diversity = min(
            1.0,
            pattern.distinct_mission_count / max(1, _MAX_MISSION_COUNT // 2),
        )

        # Prefer stronger evidence levels
        strength_bonus = 0.0
        if EvidenceLevel.OPERATOR_LABEL.value in all_levels:
            strength_bonus = 0.3
        elif EvidenceLevel.MISSION_OUTCOME.value in all_levels:
            strength_bonus = 0.2
        elif EvidenceLevel.DETERMINISTIC_INCIDENT.value in all_levels:
            strength_bonus = 0.1

        diversity = (
            0.3 * level_diversity
            + 0.3 * incident_diversity
            + 0.2 * mission_diversity
            + 0.2 * strength_bonus
        )

        return min(1.0, diversity)

    def _contradiction_penalty_adjusted(self, pattern: PatternGroup) -> float:
        """
        Score that decreases as contradiction count or false positive rate rises.

        Returns 1.0 when no contradictions, approaches 0.0 with many.
        """
        if pattern.total_count == 0:
            return 0.5

        contradiction_rate = pattern.contradiction_count / pattern.total_count

        # Inverse: high contradiction -> low score
        return max(0.0, 1.0 - contradiction_rate)
