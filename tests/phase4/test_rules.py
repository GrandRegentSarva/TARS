"""
Tests for Phase 4 Rule Evaluator
=================================
Tests deterministic single-state rule evaluation.

Each test verifies that a specific rule correctly matches or does not match
a given state configuration.
"""

from __future__ import annotations

import pytest

from tars.phase4.models import IncidentType, Severity
from tars.phase4.rules import (
    check_altitude_instability,
    check_attitude_instability,
    check_battery_degradation,
    check_high_risk_state,
    check_navigation_instability,
    check_sensor_health_failure,
    check_telemetry_degradation,
    evaluate_state,
)

from .conftest import make_state


# =============================================================================
# Navigation Instability
# =============================================================================

class TestNavigationInstability:
    """Test navigation instability rule."""

    def test_no_match_nominal_gps(self):
        state = make_state(phase="cruise", gps_quality="normal")
        matches = check_navigation_instability(state)
        assert len(matches) == 0

    def test_no_match_ground_phase(self):
        state = make_state(phase="preflight", gps_quality="weak")
        matches = check_navigation_instability(state)
        assert len(matches) == 0

    def test_weak_gps_during_cruise(self):
        state = make_state(phase="cruise", gps_quality="weak")
        matches = check_navigation_instability(state)
        assert len(matches) == 1
        assert matches[0].incident_type == IncidentType.NAVIGATION_INSTABILITY
        assert matches[0].severity == Severity.LOW

    def test_unstable_gps_during_flight(self):
        state = make_state(phase="climb", gps_quality="unstable")
        matches = check_navigation_instability(state)
        assert len(matches) == 1
        assert matches[0].severity == Severity.MEDIUM

    def test_missing_gps_during_flight(self):
        state = make_state(phase="cruise", gps_quality="missing")
        matches = check_navigation_instability(state)
        assert len(matches) == 1
        assert matches[0].severity == Severity.HIGH

    def test_weak_gps_with_elevated_risk(self):
        state = make_state(phase="cruise", gps_quality="weak", risk=0.65)
        matches = check_navigation_instability(state)
        assert len(matches) == 1
        assert matches[0].severity == Severity.MEDIUM
        assert any("elevated" in e.lower() for e in matches[0].evidence)

    def test_weak_gps_with_attitude_degradation(self):
        state = make_state(
            phase="cruise", gps_quality="weak", attitude_stability="weak"
        )
        matches = check_navigation_instability(state)
        assert len(matches) == 1
        assert matches[0].severity == Severity.HIGH

    def test_weak_gps_with_altitude_degradation(self):
        state = make_state(
            phase="cruise", gps_quality="weak", altitude_stability="unstable"
        )
        matches = check_navigation_instability(state)
        assert len(matches) == 1
        assert matches[0].severity == Severity.HIGH

    def test_no_match_landed_phase(self):
        state = make_state(phase="landed", gps_quality="missing")
        matches = check_navigation_instability(state)
        assert len(matches) == 0


# =============================================================================
# Battery Degradation
# =============================================================================

class TestBatteryDegradation:
    """Test battery degradation rule."""

    def test_no_match_normal_battery(self):
        state = make_state(battery_level="normal")
        matches = check_battery_degradation(state)
        assert len(matches) == 0

    def test_weak_battery(self):
        state = make_state(battery_level="weak", battery_percent=25.0)
        matches = check_battery_degradation(state)
        assert len(matches) == 1
        assert matches[0].incident_type == IncidentType.BATTERY_DEGRADATION
        assert matches[0].severity == Severity.MEDIUM

    def test_unstable_battery(self):
        state = make_state(battery_level="unstable", battery_percent=30.0)
        matches = check_battery_degradation(state)
        assert len(matches) == 1
        assert matches[0].severity == Severity.HIGH

    def test_critical_battery_percent(self):
        state = make_state(battery_level="unstable", battery_percent=10.0)
        matches = check_battery_degradation(state)
        assert len(matches) == 1
        assert matches[0].severity == Severity.CRITICAL

    def test_battery_evidence_includes_percent(self):
        state = make_state(battery_level="weak", battery_percent=22.5)
        matches = check_battery_degradation(state)
        assert any("22.5%" in e for e in matches[0].evidence)


# =============================================================================
# Attitude Instability
# =============================================================================

class TestAttitudeInstability:
    """Test attitude instability rule."""

    def test_no_match_normal_attitude(self):
        state = make_state(phase="cruise", attitude_stability="normal")
        matches = check_attitude_instability(state)
        assert len(matches) == 0

    def test_no_match_ground_phase(self):
        state = make_state(phase="landed", attitude_stability="weak")
        matches = check_attitude_instability(state)
        assert len(matches) == 0

    def test_weak_attitude_during_cruise(self):
        state = make_state(phase="cruise", attitude_stability="weak")
        matches = check_attitude_instability(state)
        assert len(matches) == 1
        assert matches[0].incident_type == IncidentType.ATTITUDE_INSTABILITY
        assert matches[0].severity == Severity.MEDIUM

    def test_unstable_attitude_during_flight(self):
        state = make_state(phase="climb", attitude_stability="unstable")
        matches = check_attitude_instability(state)
        assert len(matches) == 1
        assert matches[0].severity == Severity.HIGH

    def test_high_roll_evidence(self):
        state = make_state(
            phase="cruise", attitude_stability="weak", roll_abs_deg=30.0
        )
        matches = check_attitude_instability(state)
        assert any("roll" in e.lower() for e in matches[0].evidence)

    def test_high_pitch_evidence(self):
        state = make_state(
            phase="cruise", attitude_stability="weak", pitch_abs_deg=28.0
        )
        matches = check_attitude_instability(state)
        assert any("pitch" in e.lower() for e in matches[0].evidence)


# =============================================================================
# Altitude Instability
# =============================================================================

class TestAltitudeInstability:
    """Test altitude instability rule."""

    def test_no_match_normal_altitude(self):
        state = make_state(altitude_stability="normal")
        matches = check_altitude_instability(state)
        assert len(matches) == 0

    def test_unstable_altitude(self):
        state = make_state(altitude_stability="unstable", phase="cruise")
        matches = check_altitude_instability(state)
        assert len(matches) == 1
        assert matches[0].incident_type == IncidentType.ALTITUDE_INSTABILITY
        assert matches[0].severity == Severity.MEDIUM

    def test_unstable_altitude_near_ground(self):
        state = make_state(
            altitude_stability="unstable",
            phase="landing",
            relative_altitude_m=3.0,
        )
        matches = check_altitude_instability(state)
        assert len(matches) == 1
        assert matches[0].severity == Severity.HIGH

    def test_weak_altitude_no_match(self):
        """Only 'unstable' triggers, not 'weak'."""
        state = make_state(altitude_stability="weak")
        matches = check_altitude_instability(state)
        assert len(matches) == 0


# =============================================================================
# Sensor Health Failure
# =============================================================================

class TestSensorHealthFailure:
    """Test sensor health failure rule."""

    def test_no_match_nominal_health(self):
        state = make_state(health="nominal")
        matches = check_sensor_health_failure(state)
        assert len(matches) == 0

    def test_no_match_degraded_health(self):
        state = make_state(health="degraded")
        matches = check_sensor_health_failure(state)
        assert len(matches) == 0

    def test_critical_health_with_sensor_reason(self):
        state = make_state(
            health="critical",
            reasons=["Global position not ok", "GPS signal missing"],
        )
        matches = check_sensor_health_failure(state)
        assert len(matches) == 1
        assert matches[0].incident_type == IncidentType.SENSOR_HEALTH_FAILURE
        assert matches[0].severity == Severity.CRITICAL

    def test_critical_health_evidence_includes_reasons(self):
        state = make_state(
            health="critical",
            reasons=["Magnetometer calibration failed"],
        )
        matches = check_sensor_health_failure(state)
        assert len(matches) == 1
        assert any("failed" in e.lower() for e in matches[0].evidence)

    def test_no_match_battery_only_critical(self):
        """Battery-only critical state must NOT produce sensor_health_failure."""
        state = make_state(
            health="critical",
            reasons=["Battery level critical"],
            battery_level="unstable",
            battery_percent=8.0,
        )
        matches = check_sensor_health_failure(state)
        assert len(matches) == 0

    def test_no_match_critical_no_reasons(self):
        """Critical health with no reasons should not produce sensor incident."""
        state = make_state(health="critical", reasons=[])
        matches = check_sensor_health_failure(state)
        assert len(matches) == 0

    def test_match_accelerometer_failure(self):
        state = make_state(
            health="critical",
            reasons=["Accelerometer sensor failed"],
        )
        matches = check_sensor_health_failure(state)
        assert len(matches) == 1

    def test_match_gps_position_keyword(self):
        """Reason mentioning 'position' should match even without 'fail'."""
        state = make_state(
            health="critical",
            reasons=["Global position not ok"],
        )
        matches = check_sensor_health_failure(state)
        assert len(matches) == 1


# =============================================================================
# Telemetry Degradation
# =============================================================================

class TestTelemetryDegradation:
    """Test telemetry degradation rule."""

    def test_no_match_all_normal(self):
        state = make_state()
        matches = check_telemetry_degradation(state)
        assert len(matches) == 0

    def test_two_missing_signals(self):
        state = make_state(gps_quality="missing", battery_level="missing")
        matches = check_telemetry_degradation(state)
        assert len(matches) == 1
        assert matches[0].incident_type == IncidentType.TELEMETRY_DEGRADATION
        assert matches[0].severity == Severity.HIGH

    def test_one_missing_signal_no_match(self):
        state = make_state(gps_quality="missing")
        matches = check_telemetry_degradation(state)
        assert len(matches) == 0

    def test_unknown_health_during_flight(self):
        state = make_state(phase="cruise", health="unknown")
        matches = check_telemetry_degradation(state)
        assert len(matches) == 1
        assert matches[0].severity == Severity.MEDIUM

    def test_unknown_health_on_ground_no_match(self):
        state = make_state(phase="preflight", health="unknown")
        matches = check_telemetry_degradation(state)
        assert len(matches) == 0


# =============================================================================
# High-Risk State
# =============================================================================

class TestHighRiskState:
    """Test high-risk state rule."""

    def test_no_match_low_risk(self):
        state = make_state(risk=0.3)
        matches = check_high_risk_state(state)
        assert len(matches) == 0

    def test_elevated_risk(self):
        state = make_state(risk=0.65)
        matches = check_high_risk_state(state)
        assert len(matches) == 1
        assert matches[0].incident_type == IncidentType.HIGH_RISK_STATE
        assert matches[0].severity == Severity.HIGH

    def test_high_risk(self):
        state = make_state(risk=0.85)
        matches = check_high_risk_state(state)
        assert len(matches) == 1
        assert matches[0].severity == Severity.CRITICAL

    def test_boundary_elevated(self):
        state = make_state(risk=0.6)
        matches = check_high_risk_state(state)
        assert len(matches) == 1

    def test_below_elevated_no_match(self):
        state = make_state(risk=0.59)
        matches = check_high_risk_state(state)
        assert len(matches) == 0


# =============================================================================
# Combined Evaluator
# =============================================================================

class TestEvaluateState:
    """Test the combined evaluate_state function."""

    def test_nominal_state_no_matches(self):
        state = make_state()
        matches = evaluate_state(state)
        assert len(matches) == 0

    def test_multiple_rules_can_match(self):
        state = make_state(
            phase="cruise",
            health="critical",
            risk=0.85,
            gps_quality="missing",
            battery_level="unstable",
            battery_percent=10.0,
            reasons=["Global position not ok", "GPS signal missing"],
        )
        matches = evaluate_state(state)
        types = {m.incident_type for m in matches}
        # Should match navigation, battery, sensor health, high risk
        assert IncidentType.NAVIGATION_INSTABILITY in types
        assert IncidentType.BATTERY_DEGRADATION in types
        assert IncidentType.SENSOR_HEALTH_FAILURE in types
        assert IncidentType.HIGH_RISK_STATE in types

    def test_critical_battery_no_sensor_incident(self):
        """Critical health from battery alone must not produce sensor incident."""
        state = make_state(
            phase="cruise",
            health="critical",
            risk=0.85,
            battery_level="unstable",
            battery_percent=8.0,
            reasons=["Battery level critical"],
        )
        matches = evaluate_state(state)
        types = {m.incident_type for m in matches}
        assert IncidentType.BATTERY_DEGRADATION in types
        assert IncidentType.SENSOR_HEALTH_FAILURE not in types

    def test_sequence_and_elapsed_preserved(self):
        state = make_state(
            sequence=42, elapsed_ms=42000, phase="cruise", gps_quality="weak"
        )
        matches = evaluate_state(state)
        assert len(matches) >= 1
        assert matches[0].sequence == 42
        assert matches[0].elapsed_ms == 42000
