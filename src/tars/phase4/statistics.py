"""
Simple Statistical Detection
=============================
Reusable helpers for rolling-window calculations and trend detection.

All functions are pure: no Redis, HTTP, or database access.
Every statistical rule is configurable and explainable.

Useful calculations:
- Rolling mean / standard deviation
- Rate of change
- Consecutive threshold violations
- Direction changes within a window (oscillation detection)
"""

from __future__ import annotations

import math
from typing import Sequence


def rolling_mean(values: Sequence[float], window: int) -> list[float]:
    """
    Compute rolling mean over a sliding window.

    Args:
        values: Sequence of numeric values.
        window: Window size (number of elements).

    Returns:
        List of rolling means. Length = len(values) - window + 1.
        Empty list if len(values) < window.
    """
    if len(values) < window or window < 1:
        return []

    result: list[float] = []
    current_sum = sum(values[:window])
    result.append(current_sum / window)

    for i in range(window, len(values)):
        current_sum += values[i] - values[i - window]
        result.append(current_sum / window)

    return result


def rolling_stddev(values: Sequence[float], window: int) -> list[float]:
    """
    Compute rolling standard deviation over a sliding window.

    Uses population stddev (N, not N-1) for consistency.

    Args:
        values: Sequence of numeric values.
        window: Window size.

    Returns:
        List of rolling stddevs. Length = len(values) - window + 1.
    """
    if len(values) < window or window < 1:
        return []

    result: list[float] = []
    for i in range(len(values) - window + 1):
        chunk = values[i : i + window]
        mean = sum(chunk) / window
        variance = sum((x - mean) ** 2 for x in chunk) / window
        result.append(math.sqrt(variance))

    return result


def rate_of_change(values: Sequence[float]) -> list[float]:
    """
    Compute rate of change between consecutive values.

    Args:
        values: Sequence of numeric values.

    Returns:
        List of deltas. Length = len(values) - 1.
    """
    if len(values) < 2:
        return []
    return [values[i + 1] - values[i] for i in range(len(values) - 1)]


def consecutive_violations(
    values: Sequence[float],
    threshold: float,
    above: bool = True,
) -> int:
    """
    Count the maximum consecutive run of threshold violations.

    Args:
        values: Sequence of numeric values.
        threshold: Threshold to compare against.
        above: If True, count values >= threshold. If False, count values <= threshold.

    Returns:
        Maximum consecutive count of violations.
    """
    max_run = 0
    current_run = 0

    for v in values:
        if (above and v >= threshold) or (not above and v <= threshold):
            current_run += 1
            max_run = max(max_run, current_run)
        else:
            current_run = 0

    return max_run


def direction_changes(values: Sequence[float], min_delta: float = 0.0) -> int:
    """
    Count direction changes (oscillations) in a sequence.

    A direction change occurs when the sign of the delta flips.
    Deltas smaller than min_delta are ignored (treated as flat).

    Args:
        values: Sequence of numeric values.
        min_delta: Minimum absolute delta to count as a direction change.

    Returns:
        Number of direction changes.
    """
    if len(values) < 3:
        return 0

    changes = 0
    prev_direction = 0  # -1 = falling, 0 = flat, 1 = rising

    for i in range(1, len(values)):
        delta = values[i] - values[i - 1]
        if abs(delta) < min_delta:
            continue

        direction = 1 if delta > 0 else -1
        if prev_direction != 0 and direction != prev_direction:
            changes += 1
        prev_direction = direction

    return changes


def detect_battery_drop_rate(
    battery_percents: Sequence[float],
    elapsed_ms_values: Sequence[int],
    threshold_pct_per_sec: float = 0.5,
) -> list[str]:
    """
    Detect unusually fast battery drain.

    Args:
        battery_percents: Battery percentage values over time.
        elapsed_ms_values: Corresponding elapsed_ms timestamps.
        threshold_pct_per_sec: Maximum acceptable drain rate (%/sec).

    Returns:
        List of evidence strings for detected anomalies.
    """
    evidence: list[str] = []
    if len(battery_percents) < 2:
        return evidence

    for i in range(1, len(battery_percents)):
        dt_sec = (elapsed_ms_values[i] - elapsed_ms_values[i - 1]) / 1000.0
        if dt_sec <= 0:
            continue
        drop = battery_percents[i - 1] - battery_percents[i]
        if drop > 0:
            rate = drop / dt_sec
            if rate > threshold_pct_per_sec:
                evidence.append(
                    f"Battery dropping at {rate:.2f}%/s "
                    f"(threshold {threshold_pct_per_sec}%/s) "
                    f"at {elapsed_ms_values[i]}ms"
                )

    return evidence


def detect_altitude_oscillation(
    altitudes: Sequence[float],
    window: int = 10,
    min_changes: int = 4,
    min_delta: float = 0.5,
) -> list[str]:
    """
    Detect altitude oscillation within a rolling window.

    Args:
        altitudes: Altitude values over time.
        window: Window size for oscillation detection.
        min_changes: Minimum direction changes to flag.
        min_delta: Minimum altitude change to count.

    Returns:
        List of evidence strings for detected oscillations.
    """
    evidence: list[str] = []
    if len(altitudes) < window:
        # Check the whole sequence if shorter than window
        changes = direction_changes(altitudes, min_delta)
        if changes >= min_changes:
            evidence.append(
                f"Altitude oscillating: {changes} direction changes "
                f"in {len(altitudes)} states"
            )
        return evidence

    for i in range(len(altitudes) - window + 1):
        chunk = altitudes[i : i + window]
        changes = direction_changes(chunk, min_delta)
        if changes >= min_changes:
            evidence.append(
                f"Altitude oscillating: {changes} direction changes "
                f"in window starting at index {i}"
            )
            break  # Report once per detection pass

    return evidence


def detect_sustained_risk(
    risk_values: Sequence[float],
    window: int = 5,
    threshold: float = 0.6,
) -> list[str]:
    """
    Detect sustained elevated risk using rolling mean.

    Args:
        risk_values: Risk score values over time.
        window: Rolling window size.
        threshold: Mean risk threshold.

    Returns:
        List of evidence strings for detected sustained risk.
    """
    evidence: list[str] = []
    means = rolling_mean(risk_values, window)

    for i, mean in enumerate(means):
        if mean >= threshold:
            evidence.append(
                f"Rolling risk mean {mean:.2f} >= {threshold} "
                f"over {window} states starting at index {i}"
            )
            break  # Report once per detection pass

    return evidence
