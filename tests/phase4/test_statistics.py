"""
Tests for Phase 4 Statistical Detection
=========================================
Tests rolling window calculations and trend detection helpers.
"""

from __future__ import annotations

import math

import pytest

from tars.phase4.statistics import (
    consecutive_violations,
    detect_altitude_oscillation,
    detect_battery_drop_rate,
    detect_sustained_risk,
    direction_changes,
    rate_of_change,
    rolling_mean,
    rolling_stddev,
)


# =============================================================================
# Rolling Mean
# =============================================================================

class TestRollingMean:
    """Test rolling mean calculation."""

    def test_basic_window(self):
        result = rolling_mean([1.0, 2.0, 3.0, 4.0, 5.0], window=3)
        assert len(result) == 3
        assert result[0] == pytest.approx(2.0)
        assert result[1] == pytest.approx(3.0)
        assert result[2] == pytest.approx(4.0)

    def test_window_equals_length(self):
        result = rolling_mean([1.0, 2.0, 3.0], window=3)
        assert len(result) == 1
        assert result[0] == pytest.approx(2.0)

    def test_window_larger_than_length(self):
        result = rolling_mean([1.0, 2.0], window=5)
        assert result == []

    def test_empty_input(self):
        result = rolling_mean([], window=3)
        assert result == []

    def test_window_of_one(self):
        result = rolling_mean([10.0, 20.0, 30.0], window=1)
        assert len(result) == 3
        assert result == [10.0, 20.0, 30.0]

    def test_constant_values(self):
        result = rolling_mean([5.0, 5.0, 5.0, 5.0], window=2)
        assert all(v == pytest.approx(5.0) for v in result)


# =============================================================================
# Rolling Standard Deviation
# =============================================================================

class TestRollingStddev:
    """Test rolling standard deviation calculation."""

    def test_constant_values_zero_stddev(self):
        result = rolling_stddev([5.0, 5.0, 5.0, 5.0], window=3)
        assert len(result) == 2
        assert all(v == pytest.approx(0.0) for v in result)

    def test_known_stddev(self):
        # [1, 2, 3] -> mean=2, variance=(1+0+1)/3=0.667, stddev=0.816
        result = rolling_stddev([1.0, 2.0, 3.0], window=3)
        assert len(result) == 1
        assert result[0] == pytest.approx(math.sqrt(2.0 / 3.0))

    def test_empty_input(self):
        result = rolling_stddev([], window=3)
        assert result == []

    def test_window_larger_than_length(self):
        result = rolling_stddev([1.0], window=3)
        assert result == []


# =============================================================================
# Rate of Change
# =============================================================================

class TestRateOfChange:
    """Test rate of change calculation."""

    def test_basic_deltas(self):
        result = rate_of_change([10.0, 12.0, 9.0, 15.0])
        assert len(result) == 3
        assert result[0] == pytest.approx(2.0)
        assert result[1] == pytest.approx(-3.0)
        assert result[2] == pytest.approx(6.0)

    def test_constant_values(self):
        result = rate_of_change([5.0, 5.0, 5.0])
        assert all(v == pytest.approx(0.0) for v in result)

    def test_single_value(self):
        result = rate_of_change([5.0])
        assert result == []

    def test_empty_input(self):
        result = rate_of_change([])
        assert result == []


# =============================================================================
# Consecutive Violations
# =============================================================================

class TestConsecutiveViolations:
    """Test consecutive threshold violation counting."""

    def test_all_above(self):
        result = consecutive_violations([0.7, 0.8, 0.9], threshold=0.6, above=True)
        assert result == 3

    def test_none_above(self):
        result = consecutive_violations([0.1, 0.2, 0.3], threshold=0.6, above=True)
        assert result == 0

    def test_mixed_run(self):
        result = consecutive_violations(
            [0.1, 0.7, 0.8, 0.9, 0.2, 0.8, 0.9],
            threshold=0.6,
            above=True,
        )
        assert result == 3  # longest run is [0.7, 0.8, 0.9]

    def test_below_threshold(self):
        result = consecutive_violations(
            [0.5, 0.3, 0.2, 0.1, 0.6],
            threshold=0.4,
            above=False,
        )
        assert result == 3  # [0.3, 0.2, 0.1]

    def test_empty_input(self):
        result = consecutive_violations([], threshold=0.5, above=True)
        assert result == 0

    def test_boundary_value(self):
        result = consecutive_violations([0.6], threshold=0.6, above=True)
        assert result == 1


# =============================================================================
# Direction Changes
# =============================================================================

class TestDirectionChanges:
    """Test direction change (oscillation) detection."""

    def test_monotonic_increasing(self):
        result = direction_changes([1.0, 2.0, 3.0, 4.0, 5.0])
        assert result == 0

    def test_monotonic_decreasing(self):
        result = direction_changes([5.0, 4.0, 3.0, 2.0, 1.0])
        assert result == 0

    def test_single_oscillation(self):
        result = direction_changes([1.0, 3.0, 2.0])
        assert result == 1

    def test_multiple_oscillations(self):
        result = direction_changes([1.0, 3.0, 1.0, 3.0, 1.0])
        assert result == 3

    def test_min_delta_filter(self):
        result = direction_changes([1.0, 1.1, 0.9, 1.2], min_delta=0.5)
        assert result == 0  # All deltas < 0.5

    def test_short_sequence(self):
        result = direction_changes([1.0, 2.0])
        assert result == 0

    def test_empty_sequence(self):
        result = direction_changes([])
        assert result == 0


# =============================================================================
# Battery Drop Rate Detection
# =============================================================================

class TestDetectBatteryDropRate:
    """Test battery drain rate detection."""

    def test_normal_drain(self):
        evidence = detect_battery_drop_rate(
            battery_percents=[90.0, 89.5, 89.0],
            elapsed_ms_values=[0, 1000, 2000],
            threshold_pct_per_sec=0.5,
        )
        assert len(evidence) == 0  # 0.5%/s is at threshold, not above

    def test_fast_drain(self):
        evidence = detect_battery_drop_rate(
            battery_percents=[90.0, 85.0, 80.0],
            elapsed_ms_values=[0, 1000, 2000],
            threshold_pct_per_sec=0.5,
        )
        assert len(evidence) == 2  # Both drops are 5%/s

    def test_no_drain(self):
        evidence = detect_battery_drop_rate(
            battery_percents=[90.0, 90.0, 90.0],
            elapsed_ms_values=[0, 1000, 2000],
        )
        assert len(evidence) == 0

    def test_single_value(self):
        evidence = detect_battery_drop_rate(
            battery_percents=[90.0],
            elapsed_ms_values=[0],
        )
        assert len(evidence) == 0


# =============================================================================
# Altitude Oscillation Detection
# =============================================================================

class TestDetectAltitudeOscillation:
    """Test altitude oscillation detection."""

    def test_stable_altitude(self):
        evidence = detect_altitude_oscillation(
            altitudes=[20.0, 20.1, 20.0, 20.1, 20.0],
            window=5,
            min_changes=4,
            min_delta=0.5,
        )
        assert len(evidence) == 0  # Deltas too small

    def test_oscillating_altitude(self):
        evidence = detect_altitude_oscillation(
            altitudes=[20.0, 22.0, 18.0, 22.0, 18.0, 22.0, 18.0, 22.0, 18.0, 22.0],
            window=10,
            min_changes=4,
            min_delta=0.5,
        )
        assert len(evidence) >= 1

    def test_short_sequence(self):
        evidence = detect_altitude_oscillation(
            altitudes=[20.0, 22.0, 18.0],
            window=10,
            min_changes=2,
            min_delta=0.5,
        )
        # Shorter than window, checks whole sequence
        assert len(evidence) == 0  # Only 1 direction change


# =============================================================================
# Sustained Risk Detection
# =============================================================================

class TestDetectSustainedRisk:
    """Test sustained risk detection."""

    def test_low_risk(self):
        evidence = detect_sustained_risk(
            risk_values=[0.1, 0.2, 0.1, 0.2, 0.1],
            window=3,
            threshold=0.6,
        )
        assert len(evidence) == 0

    def test_sustained_high_risk(self):
        evidence = detect_sustained_risk(
            risk_values=[0.7, 0.8, 0.7, 0.8, 0.7],
            window=3,
            threshold=0.6,
        )
        assert len(evidence) >= 1

    def test_brief_spike_no_detection(self):
        evidence = detect_sustained_risk(
            risk_values=[0.1, 0.1, 0.9, 0.1, 0.1],
            window=3,
            threshold=0.6,
        )
        # Mean of any 3-window: [0.1,0.1,0.9]=0.37, [0.1,0.9,0.1]=0.37, [0.9,0.1,0.1]=0.37
        assert len(evidence) == 0
