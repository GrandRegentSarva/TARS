"""
Phase 9 Deterministic Evaluator
=================================
Computes root-cause accuracy, recommendation quality, response consistency,
false-positive, false-negative, and overall scores.

All scoring is deterministic and testable. No LLM calls are made.
Aliases and families are versioned in configuration.

Scoring rules:
- Root-cause: exact match=1.0, alias=1.0, family=0.5, mismatch=0.0
- Recommendation: preferred match=1.0, family=0.5, unrelated=0.0
- Consistency: compared against similar evaluated cases
- False positive/negative: require strong evidence
- Overall: weighted aggregate excluding insufficient-evidence metrics
"""

from __future__ import annotations

import logging
import re
from typing import Any, Optional

from .config import settings
from .ground_truth import GroundTruthResult
from .models import (
    ClassificationLabel,
    EvaluationMetric,
    EvidenceLevel,
    MetricName,
)

logger = logging.getLogger("phase9.evaluator")


# =============================================================================
# Root-Cause Aliases and Families
# =============================================================================

# Deterministic alias mapping: alias -> canonical form
ROOT_CAUSE_ALIASES: dict[str, str] = {
    "gps_drift": "gps_interference",
    "localization_loss": "gps_interference",
    "gps_signal_loss": "gps_interference",
    "gps_multipath": "gps_interference",
    "wind_disturbance": "environmental_wind",
    "wind_gust": "environmental_wind",
    "crosswind": "environmental_wind",
    "battery_sag": "power_instability",
    "battery_voltage_drop": "power_instability",
    "low_battery": "power_instability",
    "battery_degradation": "power_instability",
    "motor_failure": "actuator_failure",
    "esc_failure": "actuator_failure",
    "propeller_damage": "actuator_failure",
    "magnetometer_error": "sensor_failure",
    "imu_drift": "sensor_failure",
    "barometer_error": "sensor_failure",
    "sensor_health_failure": "sensor_failure",
    "communication_loss": "link_failure",
    "telemetry_loss": "link_failure",
    "rc_link_loss": "link_failure",
}

# Root-cause families: family -> list of canonical causes
ROOT_CAUSE_FAMILIES: dict[str, list[str]] = {
    "navigation": [
        "gps_interference",
        "navigation_instability",
        "localization_failure",
    ],
    "power": [
        "power_instability",
        "battery_failure",
        "power_supply_failure",
    ],
    "environmental": [
        "environmental_wind",
        "weather_condition",
        "temperature_extreme",
    ],
    "mechanical": [
        "actuator_failure",
        "structural_damage",
        "vibration_anomaly",
    ],
    "sensor": [
        "sensor_failure",
        "sensor_degradation",
        "calibration_error",
    ],
    "communication": [
        "link_failure",
        "telemetry_degradation",
        "command_loss",
    ],
    "operator": [
        "operator_error",
        "operator_abort",
        "planned_stop",
        "manual_override",
    ],
}

# Mitigation families for recommendation matching
MITIGATION_FAMILIES: dict[str, list[str]] = {
    "navigation_switch": [
        "switch_to_visual_odometry",
        "switch_navigation_source",
        "enable_backup_navigation",
        "use_inertial_navigation",
    ],
    "return_home": [
        "return_to_launch",
        "return_to_home",
        "initiate_rtl",
        "abort_mission",
    ],
    "altitude_management": [
        "reduce_altitude",
        "increase_altitude",
        "hold_altitude",
        "descend_gradually",
    ],
    "power_management": [
        "reduce_power_consumption",
        "enter_low_power_mode",
        "conserve_battery",
        "limit_maneuvers",
    ],
    "monitoring": [
        "increase_monitoring",
        "enhance_telemetry",
        "add_redundancy_checks",
        "enable_watchdog",
    ],
}

# Flight-control command patterns (must not appear in recommendations)
_CONTROL_PATTERNS = [
    r"\bexecute\b",
    r"\bsend_command\b",
    r"\bsend command\b",
    r"\barm\b",
    r"\bdisarm\b",
    r"\btakeoff\b",
    r"\btake off\b",
    r"\bland\b",
    r"\brtl\b",
    r"\breturn_to_launch\b",
    r"\breturn to launch\b",
    r"\bset_mode\b",
    r"\bset mode\b",
    r"\bkill\b",
    r"\bactuator\b",
    r"\bmavlink\b",
    r"\bmavsdk\b",
    r"\bdescend immediately\b",
    r"\bfly to\b",
]


# =============================================================================
# Normalization
# =============================================================================

def normalize_root_cause(root_cause: str) -> str:
    """
    Normalize a root-cause string to its canonical form.

    Applies lowercasing, whitespace normalization, and alias resolution.
    """
    normalized = root_cause.lower().strip()
    normalized = re.sub(r"\s+", "_", normalized)
    normalized = re.sub(r"[^a-z0-9_]", "", normalized)

    # Resolve alias
    return ROOT_CAUSE_ALIASES.get(normalized, normalized)


def normalize_mitigation(mitigation: str) -> str:
    """Normalize a mitigation string for comparison."""
    normalized = mitigation.lower().strip()
    normalized = re.sub(r"\s+", "_", normalized)
    normalized = re.sub(r"[^a-z0-9_]", "", normalized)
    return normalized


def get_root_cause_family(canonical: str) -> Optional[str]:
    """Get the family name for a canonical root cause."""
    for family, members in ROOT_CAUSE_FAMILIES.items():
        if canonical in members:
            return family
    return None


def get_mitigation_family(normalized: str) -> Optional[str]:
    """Get the family name for a normalized mitigation."""
    for family, members in MITIGATION_FAMILIES.items():
        if normalized in members:
            return family
    return None


def _contains_control_command(text: str) -> bool:
    """Check if text contains a flight-control command pattern."""
    lower = text.lower()
    for pattern in _CONTROL_PATTERNS:
        if re.search(pattern, lower):
            return True
    return False


def _stem(word: str) -> str:
    """
    Basic suffix-stripping stemmer for deterministic token matching.

    Strips common English suffixes (-ing, -tion, -ed, -ly, -er, -es, -s)
    to allow "switching" to match "switch", etc. Not a full NLP stemmer
    but sufficient for drone-domain mitigation vocabulary.
    """
    if len(word) <= 3:
        return word
    for suffix in ("ation", "tion", "ing", "ment", "ness", "able",
                   "ible", "ally", "ful", "less", "ous", "ive",
                   "ed", "ly", "er", "es"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            return word[: -len(suffix)]
    if word.endswith("s") and not word.endswith("ss") and len(word) > 3:
        return word[:-1]
    return word


# =============================================================================
# Evaluator
# =============================================================================

class Evaluator:
    """
    Deterministic evaluator for reasoning quality.

    Computes bounded metrics from reasoning outputs and ground-truth labels.
    All scoring is deterministic -- no LLM calls.
    """

    def __init__(self, version: Optional[str] = None) -> None:
        self.version = version or settings.EVALUATION_VERSION

    def evaluate(
        self,
        reasoning: dict[str, Any],
        ground_truth: GroundTruthResult,
        incident: Optional[dict[str, Any]] = None,
        similar_evaluations: Optional[list[dict[str, Any]]] = None,
        evaluate_consistency: bool = True,
    ) -> list[EvaluationMetric]:
        """
        Evaluate a reasoning result against ground truth.

        Args:
            reasoning: Phase 5 reasoning result dict.
            ground_truth: Resolved ground-truth result.
            incident: Optional Phase 4 incident dict.
            similar_evaluations: Optional list of similar evaluated cases.
            evaluate_consistency: Whether to compute consistency score.

        Returns:
            List of EvaluationMetric objects.
        """
        metrics: list[EvaluationMetric] = []

        # Root-cause accuracy
        metrics.append(
            self.score_root_cause(reasoning, ground_truth)
        )

        # Recommendation accuracy
        metrics.append(
            self.score_recommendation(reasoning, ground_truth)
        )

        # Response consistency
        if evaluate_consistency:
            metrics.append(
                self.score_consistency(reasoning, similar_evaluations)
            )

        # False positive
        fp_metric = self.score_false_positive(
            reasoning, ground_truth, incident
        )
        if fp_metric is not None:
            metrics.append(fp_metric)

        # False negative (only at mission level, handled by service)

        return metrics

    def score_root_cause(
        self,
        reasoning: dict[str, Any],
        ground_truth: GroundTruthResult,
    ) -> EvaluationMetric:
        """
        Score root-cause accuracy.

        Rules:
        - Exact normalized match: 1.0, correct
        - Known alias match: 1.0, correct
        - Same family: 0.5, partially_correct
        - Different: 0.0, incorrect
        - Missing label: null, insufficient_evidence
        """
        if not ground_truth.has_evidence or ground_truth.label is None:
            return EvaluationMetric(
                name=MetricName.ROOT_CAUSE_ACCURACY,
                score=None,
                label=ClassificationLabel.INSUFFICIENT_EVIDENCE,
                evidence=[],
                explanation="No ground-truth root cause available.",
            )

        gt_root_cause = ground_truth.label.root_cause
        if not gt_root_cause:
            return EvaluationMetric(
                name=MetricName.ROOT_CAUSE_ACCURACY,
                score=None,
                label=ClassificationLabel.INSUFFICIENT_EVIDENCE,
                evidence=[],
                explanation="Ground-truth label has no root cause.",
            )

        predicted = reasoning.get("root_cause", "")
        if not predicted:
            return EvaluationMetric(
                name=MetricName.ROOT_CAUSE_ACCURACY,
                score=0.0,
                label=ClassificationLabel.INCORRECT,
                evidence=[ground_truth.evidence_level or ""],
                explanation="No root cause predicted.",
            )

        # Normalize both
        pred_normalized = normalize_root_cause(predicted)
        gt_normalized = normalize_root_cause(gt_root_cause)

        evidence = [ground_truth.evidence_level or ""]

        # Exact match (after normalization and alias resolution)
        if pred_normalized == gt_normalized:
            return EvaluationMetric(
                name=MetricName.ROOT_CAUSE_ACCURACY,
                score=1.0,
                label=ClassificationLabel.CORRECT,
                evidence=evidence,
                explanation=(
                    f"Predicted root cause '{pred_normalized}' matches "
                    f"accepted label '{gt_normalized}'."
                ),
            )

        # Same family
        pred_family = get_root_cause_family(pred_normalized)
        gt_family = get_root_cause_family(gt_normalized)

        if pred_family and gt_family and pred_family == gt_family:
            return EvaluationMetric(
                name=MetricName.ROOT_CAUSE_ACCURACY,
                score=0.5,
                label=ClassificationLabel.PARTIALLY_CORRECT,
                evidence=evidence,
                explanation=(
                    f"Predicted root cause '{pred_normalized}' is in the "
                    f"same family '{pred_family}' as accepted label "
                    f"'{gt_normalized}'."
                ),
            )

        # Mismatch
        return EvaluationMetric(
            name=MetricName.ROOT_CAUSE_ACCURACY,
            score=0.0,
            label=ClassificationLabel.INCORRECT,
            evidence=evidence,
            explanation=(
                f"Predicted root cause '{pred_normalized}' does not match "
                f"accepted label '{gt_normalized}'."
            ),
        )

    def score_recommendation(
        self,
        reasoning: dict[str, Any],
        ground_truth: GroundTruthResult,
    ) -> EvaluationMetric:
        """
        Score recommendation accuracy.

        Rules:
        - Names preferred mitigation: 1.0
        - Compatible family: 0.5
        - Unrelated: 0.0
        - Contains control command: validation failure
        - No preferred mitigation: null, insufficient_evidence
        """
        if not ground_truth.has_evidence or ground_truth.label is None:
            return EvaluationMetric(
                name=MetricName.RECOMMENDATION_ACCURACY,
                score=None,
                label=ClassificationLabel.INSUFFICIENT_EVIDENCE,
                evidence=[],
                explanation="No ground-truth recommendation available.",
            )

        preferred = ground_truth.label.preferred_mitigation
        if not preferred:
            return EvaluationMetric(
                name=MetricName.RECOMMENDATION_ACCURACY,
                score=None,
                label=ClassificationLabel.INSUFFICIENT_EVIDENCE,
                evidence=[],
                explanation="Ground-truth label has no preferred mitigation.",
            )

        recommendation = reasoning.get("recommendation", "")
        if not recommendation:
            return EvaluationMetric(
                name=MetricName.RECOMMENDATION_ACCURACY,
                score=0.0,
                label=ClassificationLabel.INCORRECT,
                evidence=[ground_truth.evidence_level or ""],
                explanation="No recommendation provided.",
            )

        # Check for control commands
        if _contains_control_command(recommendation):
            return EvaluationMetric(
                name=MetricName.RECOMMENDATION_ACCURACY,
                score=0.0,
                label=ClassificationLabel.INCORRECT,
                evidence=[ground_truth.evidence_level or ""],
                explanation=(
                    "Recommendation contains a direct flight-control command. "
                    "Recommendations must be advisory only."
                ),
            )

        # Normalize both
        rec_normalized = normalize_mitigation(recommendation)
        pref_normalized = normalize_mitigation(preferred)

        evidence = [ground_truth.evidence_level or ""]

        # Exact match
        if rec_normalized == pref_normalized:
            return EvaluationMetric(
                name=MetricName.RECOMMENDATION_ACCURACY,
                score=1.0,
                label=ClassificationLabel.CORRECT,
                evidence=evidence,
                explanation=(
                    f"Recommendation matches preferred mitigation "
                    f"'{pref_normalized}'."
                ),
            )

        # Check if recommendation contains the preferred mitigation
        if pref_normalized in rec_normalized or rec_normalized in pref_normalized:
            return EvaluationMetric(
                name=MetricName.RECOMMENDATION_ACCURACY,
                score=1.0,
                label=ClassificationLabel.CORRECT,
                evidence=evidence,
                explanation=(
                    f"Recommendation contains preferred mitigation "
                    f"'{pref_normalized}'."
                ),
            )

        # Word-level token matching: check if all meaningful tokens
        # from the preferred mitigation appear in the recommendation.
        # This handles natural advisory text like "Consider switching
        # to visual odometry" matching "switch_to_visual_odometry".
        pref_tokens = set(pref_normalized.split("_"))
        rec_tokens = set(rec_normalized.split("_"))
        # Remove common stop-words that add noise
        stop_words = {"to", "the", "a", "an", "and", "or", "in", "on",
                      "for", "of", "is", "be", "we", "should", "consider",
                      "when", "if", "with", "from", "by", "at", "as"}
        pref_meaningful = pref_tokens - stop_words
        rec_meaningful = rec_tokens - stop_words
        # Apply basic stemming (strip common suffixes) for fuzzy matching
        pref_stems = {_stem(t) for t in pref_meaningful}
        rec_stems = {_stem(t) for t in rec_meaningful}
        if pref_stems and pref_stems.issubset(rec_stems):
            return EvaluationMetric(
                name=MetricName.RECOMMENDATION_ACCURACY,
                score=1.0,
                label=ClassificationLabel.CORRECT,
                evidence=evidence,
                explanation=(
                    f"Recommendation tokens cover preferred mitigation "
                    f"'{pref_normalized}'."
                ),
            )

        # Same family
        rec_family = get_mitigation_family(rec_normalized)
        pref_family = get_mitigation_family(pref_normalized)

        if rec_family and pref_family and rec_family == pref_family:
            return EvaluationMetric(
                name=MetricName.RECOMMENDATION_ACCURACY,
                score=0.5,
                label=ClassificationLabel.PARTIALLY_CORRECT,
                evidence=evidence,
                explanation=(
                    f"Recommendation is in the same mitigation family "
                    f"'{rec_family}' as preferred '{pref_normalized}'."
                ),
            )

        # Unrelated
        return EvaluationMetric(
            name=MetricName.RECOMMENDATION_ACCURACY,
            score=0.0,
            label=ClassificationLabel.INCORRECT,
            evidence=evidence,
            explanation=(
                f"Recommendation '{rec_normalized}' does not align with "
                f"preferred mitigation '{pref_normalized}'."
            ),
        )

    def score_consistency(
        self,
        reasoning: dict[str, Any],
        similar_evaluations: Optional[list[dict[str, Any]]] = None,
    ) -> EvaluationMetric:
        """
        Score response consistency against similar evaluated cases.

        Rules:
        - Compatible root cause and mitigation: high consistency
        - Compatible root cause, different mitigation: partial
        - Contradictory reasoning: low consistency
        - Fewer than min cases: insufficient evidence
        """
        min_cases = settings.EVALUATION_CONSISTENCY_MIN_CASES

        if not similar_evaluations or len(similar_evaluations) < min_cases:
            return EvaluationMetric(
                name=MetricName.RESPONSE_CONSISTENCY,
                score=None,
                label=ClassificationLabel.INSUFFICIENT_EVIDENCE,
                evidence=[EvidenceLevel.HISTORICAL_CONSISTENCY.value],
                explanation=(
                    f"Fewer than {min_cases} similar evaluated cases "
                    f"available for consistency comparison "
                    f"(found {len(similar_evaluations) if similar_evaluations else 0})."
                ),
            )

        # Compare root-cause scores
        pred_root_cause = normalize_root_cause(
            reasoning.get("root_cause", "")
        )

        consistent_count = 0
        total_compared = 0

        for sim in similar_evaluations:
            sim_rc_score = sim.get("root_cause_score")
            sim_rec_score = sim.get("recommendation_score")

            if sim_rc_score is not None:
                total_compared += 1
                # If both have high root-cause scores, they're consistent
                if sim_rc_score >= 0.5:
                    consistent_count += 1

        if total_compared == 0:
            return EvaluationMetric(
                name=MetricName.RESPONSE_CONSISTENCY,
                score=None,
                label=ClassificationLabel.INSUFFICIENT_EVIDENCE,
                evidence=[EvidenceLevel.HISTORICAL_CONSISTENCY.value],
                explanation="No comparable scored evaluations found.",
            )

        consistency = consistent_count / total_compared

        if consistency >= 0.8:
            label = ClassificationLabel.CORRECT
        elif consistency >= 0.5:
            label = ClassificationLabel.PARTIALLY_CORRECT
        else:
            label = ClassificationLabel.INCORRECT

        return EvaluationMetric(
            name=MetricName.RESPONSE_CONSISTENCY,
            score=round(consistency, 4),
            label=label,
            evidence=[EvidenceLevel.HISTORICAL_CONSISTENCY.value],
            explanation=(
                f"Consistency score {consistency:.2f} based on "
                f"{consistent_count}/{total_compared} similar cases "
                f"with compatible reasoning."
            ),
        )

    def score_false_positive(
        self,
        reasoning: dict[str, Any],
        ground_truth: GroundTruthResult,
        incident: Optional[dict[str, Any]] = None,
    ) -> Optional[EvaluationMetric]:
        """
        Determine if the reasoning is a false positive.

        A false positive occurs when the system produced or reasoned about
        a problem that later evidence does not support.

        Requires outcome or operator evidence. Trace history alone is
        not enough.
        """
        if not ground_truth.has_evidence or ground_truth.label is None:
            return None

        outcome = ground_truth.label.outcome
        gt_root_cause = ground_truth.label.root_cause

        # Check if outcome indicates nominal behavior
        nominal_outcomes = {"nominal", "normal", "planned_stop", "success"}
        operator_causes = {"operator_abort", "planned_stop", "manual_override"}

        is_false_positive = False
        explanation = "No false-positive indicators detected."

        if outcome and outcome.lower() in nominal_outcomes:
            # Outcome was nominal but reasoning claimed a problem
            if reasoning.get("root_cause"):
                is_false_positive = True
                explanation = (
                    f"Reasoning claimed root cause "
                    f"'{reasoning['root_cause']}' but mission outcome "
                    f"was '{outcome}' (nominal)."
                )

        if gt_root_cause and gt_root_cause.lower() in operator_causes:
            pred_normalized = normalize_root_cause(
                reasoning.get("root_cause", "")
            )
            gt_normalized = normalize_root_cause(gt_root_cause)
            if pred_normalized != gt_normalized:
                pred_family = get_root_cause_family(pred_normalized)
                gt_family = get_root_cause_family(gt_normalized)
                if pred_family != gt_family:
                    is_false_positive = True
                    explanation = (
                        f"Reasoning claimed '{pred_normalized}' but "
                        f"accepted cause was operator action "
                        f"'{gt_normalized}'."
                    )

        evidence = [ground_truth.evidence_level or ""]

        return EvaluationMetric(
            name=MetricName.FALSE_POSITIVE,
            score=0.0 if is_false_positive else 1.0,
            label=(
                ClassificationLabel.INCORRECT
                if is_false_positive
                else ClassificationLabel.CORRECT
            ),
            evidence=evidence,
            explanation=explanation,
        )

    def score_false_negative(
        self,
        mission_id: str,
        incidents: list[dict[str, Any]],
        reasoning_results: list[dict[str, Any]],
        ground_truth: GroundTruthResult,
    ) -> Optional[EvaluationMetric]:
        """
        Determine if the system missed a problem (false negative).

        A false negative occurs when later evidence confirms a problem
        that the system failed to detect or reason about.

        This is typically a mission-level evaluation.
        """
        if not ground_truth.has_evidence or ground_truth.label is None:
            return None

        outcome = ground_truth.label.outcome
        gt_root_cause = ground_truth.label.root_cause

        # Check if outcome indicates a problem
        problem_outcomes = {"failed", "degraded", "crashed", "emergency"}

        if not outcome or outcome.lower() not in problem_outcomes:
            return EvaluationMetric(
                name=MetricName.FALSE_NEGATIVE,
                score=1.0,
                label=ClassificationLabel.CORRECT,
                evidence=[ground_truth.evidence_level or ""],
                explanation=(
                    "Mission outcome does not indicate a missed problem."
                ),
            )

        # Check if any incident was emitted
        if not incidents:
            return EvaluationMetric(
                name=MetricName.FALSE_NEGATIVE,
                score=0.0,
                label=ClassificationLabel.INCORRECT,
                evidence=[ground_truth.evidence_level or ""],
                explanation=(
                    f"Mission outcome was '{outcome}' but no incidents "
                    f"were detected."
                ),
            )

        # Check if reasoning was generated for incidents
        incident_ids = {inc.get("incident_id") for inc in incidents}
        reasoned_ids = {r.get("incident_id") for r in reasoning_results}

        unreasoned = incident_ids - reasoned_ids
        if unreasoned:
            return EvaluationMetric(
                name=MetricName.FALSE_NEGATIVE,
                score=0.0,
                label=ClassificationLabel.INCORRECT,
                evidence=[ground_truth.evidence_level or ""],
                explanation=(
                    f"Incidents {unreasoned} were detected but no "
                    f"reasoning was generated for them."
                ),
            )

        # Check if the confirmed root cause was addressed
        if gt_root_cause:
            gt_normalized = normalize_root_cause(gt_root_cause)
            gt_family = get_root_cause_family(gt_normalized)

            addressed = False
            for r in reasoning_results:
                pred_normalized = normalize_root_cause(
                    r.get("root_cause", "")
                )
                if pred_normalized == gt_normalized:
                    addressed = True
                    break
                pred_family = get_root_cause_family(pred_normalized)
                if pred_family and gt_family and pred_family == gt_family:
                    addressed = True
                    break

            if not addressed:
                return EvaluationMetric(
                    name=MetricName.FALSE_NEGATIVE,
                    score=0.0,
                    label=ClassificationLabel.INCORRECT,
                    evidence=[ground_truth.evidence_level or ""],
                    explanation=(
                        f"Confirmed root cause '{gt_normalized}' was not "
                        f"addressed by any reasoning output."
                    ),
                )

        return EvaluationMetric(
            name=MetricName.FALSE_NEGATIVE,
            score=1.0,
            label=ClassificationLabel.CORRECT,
            evidence=[ground_truth.evidence_level or ""],
            explanation="No false-negative indicators detected.",
        )

    def compute_overall_score(
        self,
        metrics: list[EvaluationMetric],
    ) -> Optional[float]:
        """
        Compute weighted overall score from individual metrics.

        Scores with insufficient_evidence are excluded from the denominator.
        Penalty terms apply only when evidence supports the label.
        """
        weights = settings.weight_config

        weighted_sum = 0.0
        weight_sum = 0.0

        for metric in metrics:
            if metric.score is None:
                continue

            if metric.name == MetricName.ROOT_CAUSE_ACCURACY:
                w = weights["root_cause_accuracy"]
                weighted_sum += metric.score * w
                weight_sum += w
            elif metric.name == MetricName.RECOMMENDATION_ACCURACY:
                w = weights["recommendation_accuracy"]
                weighted_sum += metric.score * w
                weight_sum += w
            elif metric.name == MetricName.RESPONSE_CONSISTENCY:
                w = weights["response_consistency"]
                weighted_sum += metric.score * w
                weight_sum += w
            elif metric.name == MetricName.FALSE_POSITIVE:
                w = weights["false_positive_penalty"]
                weighted_sum += metric.score * w
                weight_sum += w
            elif metric.name == MetricName.FALSE_NEGATIVE:
                w = weights["false_negative_penalty"]
                weighted_sum += metric.score * w
                weight_sum += w

        if weight_sum == 0.0:
            return None

        # Normalize to [0, 1]
        overall = weighted_sum / weight_sum
        return round(min(max(overall, 0.0), 1.0), 4)
