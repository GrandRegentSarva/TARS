"""
Risk & Health Assessment Tests
==============================
Tests for deterministic health, signal, and risk computation.

Coverage:
- Nominal health with good telemetry
- Critical health with low battery
- Critical health with GPS loss during flight
- Critical health with health flag failure during flight
- Degraded health with low battery (< 30%)
- Degraded health with low GPS satellites
- Degraded health with high attitude in cruise
- Unknown health with missing core telemetry
- Risk score increases with GPS degradation
- Risk score increases with low battery
- Risk score clamped to 1.0
- Missing telemetry produces bounded risk, not crashes
"""

from __future__ import annotations

import pytest

from tars.phase3.models import (
    HealthStatus,
    MissionPhase,
    SignalQuality,
)
from tars.phase3.risk import (
    compute_health,
    compute_risk,
    compute_signals,
    extract_metrics,
)

from .conftest import make_telemetry


class TestExtractMetrics:
    """Test metric extraction from telemetry."""

    def test_full_telemetry(self):
        """All metrics extracted from complete telemetry."""
        telemetry = make_telemetry()
        metrics = extract_metrics(telemetry)

        assert metrics.relative_altitude_m == 20.0
        assert metrics.battery_percent == 85.0
        assert metrics.gps_satellites == 12
        assert metrics.roll_abs_deg == 1.0
        assert metrics.pitch_abs_deg == 0.5
        assert metrics.ground_speed_m_s is not None
        assert metrics.ground_speed_m_s > 0

    def test_missing_position(self):
        """Missing position → altitude is None."""
        telemetry = make_telemetry()
        del telemetry["position"]
        metrics = extract_metrics(telemetry)
        assert metrics.relative_altitude_m is None

    def test_missing_battery(self):
        """Missing battery → battery_percent is None."""
        telemetry = make_telemetry()
        del telemetry["battery"]
        metrics = extract_metrics(telemetry)
        assert metrics.battery_percent is None

    def test_missing_gps(self):
        """Missing GPS → gps_satellites is None."""
        telemetry = make_telemetry()
        del telemetry["gps"]
        metrics = extract_metrics(telemetry)
        assert metrics.gps_satellites is None


class TestComputeSignals:
    """Test signal quality computation."""

    def test_normal_signals(self):
        """Good telemetry → all normal signals."""
        telemetry = make_telemetry()
        metrics = extract_metrics(telemetry)
        signals = compute_signals(telemetry, metrics, MissionPhase.CRUISE)

        assert signals.gps_quality == SignalQuality.NORMAL
        assert signals.battery_level == SignalQuality.NORMAL
        assert signals.altitude_stability == SignalQuality.NORMAL
        assert signals.attitude_stability == SignalQuality.NORMAL

    def test_weak_gps(self):
        """Low satellites → weak GPS signal."""
        telemetry = make_telemetry(gps_satellites=4)
        metrics = extract_metrics(telemetry)
        signals = compute_signals(telemetry, metrics, MissionPhase.CRUISE)
        assert signals.gps_quality == SignalQuality.WEAK

    def test_missing_gps(self):
        """No GPS data → missing GPS signal."""
        telemetry = make_telemetry()
        del telemetry["gps"]
        metrics = extract_metrics(telemetry)
        signals = compute_signals(telemetry, metrics, MissionPhase.CRUISE)
        assert signals.gps_quality == SignalQuality.MISSING

    def test_gps_no_fix(self):
        """NO_FIX → missing GPS signal."""
        telemetry = make_telemetry(gps_fix="NO_FIX")
        metrics = extract_metrics(telemetry)
        signals = compute_signals(telemetry, metrics, MissionPhase.CRUISE)
        assert signals.gps_quality == SignalQuality.MISSING

    def test_low_battery_signal(self):
        """Battery < 30% → weak battery signal."""
        telemetry = make_telemetry(battery_percent=25.0)
        metrics = extract_metrics(telemetry)
        signals = compute_signals(telemetry, metrics, MissionPhase.CRUISE)
        assert signals.battery_level == SignalQuality.WEAK

    def test_critical_battery_signal(self):
        """Battery < 15% → unstable battery signal."""
        telemetry = make_telemetry(battery_percent=10.0)
        metrics = extract_metrics(telemetry)
        signals = compute_signals(telemetry, metrics, MissionPhase.CRUISE)
        assert signals.battery_level == SignalQuality.UNSTABLE


class TestComputeHealth:
    """Test health status computation."""

    def test_nominal_health(self):
        """Good telemetry → nominal health."""
        telemetry = make_telemetry()
        metrics = extract_metrics(telemetry)
        health, reasons = compute_health(telemetry, metrics, MissionPhase.CRUISE)
        assert health == HealthStatus.NOMINAL
        assert reasons == []

    def test_unknown_missing_core(self):
        """Missing core telemetry → unknown health."""
        telemetry = make_telemetry()
        del telemetry["position"]
        metrics = extract_metrics(telemetry)
        health, reasons = compute_health(telemetry, metrics, MissionPhase.CRUISE)
        assert health == HealthStatus.UNKNOWN
        assert len(reasons) > 0

    def test_critical_low_battery(self):
        """Battery < 15% → critical health."""
        telemetry = make_telemetry(battery_percent=10.0)
        metrics = extract_metrics(telemetry)
        health, reasons = compute_health(telemetry, metrics, MissionPhase.CRUISE)
        assert health == HealthStatus.CRITICAL
        assert any("battery" in r.lower() for r in reasons)

    def test_critical_gps_loss_in_flight(self):
        """GPS NO_FIX during flight → critical health."""
        telemetry = make_telemetry(gps_fix="NO_FIX")
        metrics = extract_metrics(telemetry)
        health, reasons = compute_health(telemetry, metrics, MissionPhase.CRUISE)
        assert health == HealthStatus.CRITICAL
        assert any("gps" in r.lower() for r in reasons)

    def test_gps_loss_in_preflight_not_critical(self):
        """GPS NO_FIX during preflight → not critical (nominal or degraded)."""
        telemetry = make_telemetry(gps_fix="NO_FIX", altitude=0.8, flight_mode="HOLD")
        metrics = extract_metrics(telemetry)
        health, reasons = compute_health(telemetry, metrics, MissionPhase.PREFLIGHT)
        assert health != HealthStatus.CRITICAL

    def test_critical_health_flag_false(self):
        """Health flag false during flight → critical."""
        telemetry = make_telemetry(
            health_flags={
                "is_gyrometer_calibration_ok": False,
                "is_accelerometer_calibration_ok": True,
                "is_magnetometer_calibration_ok": True,
                "is_home_position_ok": True,
                "is_global_position_ok": True,
            }
        )
        metrics = extract_metrics(telemetry)
        health, reasons = compute_health(telemetry, metrics, MissionPhase.CRUISE)
        assert health == HealthStatus.CRITICAL
        assert any("gyrometer" in r.lower() for r in reasons)

    def test_degraded_low_battery(self):
        """Battery < 30% but >= 15% → degraded."""
        telemetry = make_telemetry(battery_percent=25.0)
        metrics = extract_metrics(telemetry)
        health, reasons = compute_health(telemetry, metrics, MissionPhase.CRUISE)
        assert health == HealthStatus.DEGRADED
        assert any("battery" in r.lower() for r in reasons)

    def test_degraded_low_gps_satellites(self):
        """GPS satellites < 6 during flight → degraded."""
        telemetry = make_telemetry(gps_satellites=4)
        metrics = extract_metrics(telemetry)
        health, reasons = compute_health(telemetry, metrics, MissionPhase.CRUISE)
        assert health == HealthStatus.DEGRADED
        assert any("gps" in r.lower() or "satellite" in r.lower() for r in reasons)

    def test_degraded_high_attitude_in_cruise(self):
        """Roll > 20° in cruise → degraded."""
        telemetry = make_telemetry(roll_deg=25.0)
        metrics = extract_metrics(telemetry)
        health, reasons = compute_health(telemetry, metrics, MissionPhase.CRUISE)
        assert health == HealthStatus.DEGRADED
        assert any("roll" in r.lower() for r in reasons)


class TestComputeRisk:
    """Test risk score computation."""

    def test_nominal_risk(self):
        """Good telemetry → low risk."""
        telemetry = make_telemetry()
        metrics = extract_metrics(telemetry)
        risk, reasons = compute_risk(telemetry, metrics, MissionPhase.CRUISE)
        assert risk < 0.3
        assert reasons == []

    def test_gps_missing_increases_risk(self):
        """Missing GPS → significant risk increase."""
        telemetry = make_telemetry()
        del telemetry["gps"]
        metrics = extract_metrics(telemetry)
        risk, reasons = compute_risk(telemetry, metrics, MissionPhase.CRUISE)
        assert risk >= 0.45
        assert any("gps" in r.lower() for r in reasons)

    def test_gps_no_fix_increases_risk(self):
        """GPS NO_FIX → significant risk increase."""
        telemetry = make_telemetry(gps_fix="NO_FIX")
        metrics = extract_metrics(telemetry)
        risk, reasons = compute_risk(telemetry, metrics, MissionPhase.CRUISE)
        assert risk >= 0.45

    def test_low_gps_satellites_increases_risk(self):
        """GPS satellites < 6 → moderate risk increase."""
        telemetry = make_telemetry(gps_satellites=4)
        metrics = extract_metrics(telemetry)
        risk, reasons = compute_risk(telemetry, metrics, MissionPhase.CRUISE)
        assert risk >= 0.20

    def test_critical_battery_increases_risk(self):
        """Battery < 15% → significant risk increase."""
        telemetry = make_telemetry(battery_percent=10.0)
        metrics = extract_metrics(telemetry)
        risk, reasons = compute_risk(telemetry, metrics, MissionPhase.CRUISE)
        assert risk >= 0.40

    def test_low_battery_increases_risk(self):
        """Battery < 30% → moderate risk increase."""
        telemetry = make_telemetry(battery_percent=25.0)
        metrics = extract_metrics(telemetry)
        risk, reasons = compute_risk(telemetry, metrics, MissionPhase.CRUISE)
        assert risk >= 0.20

    def test_health_flag_false_increases_risk(self):
        """Health flag false → significant risk increase."""
        telemetry = make_telemetry(
            health_flags={
                "is_gyrometer_calibration_ok": False,
                "is_accelerometer_calibration_ok": True,
                "is_magnetometer_calibration_ok": True,
                "is_home_position_ok": True,
                "is_global_position_ok": True,
            }
        )
        metrics = extract_metrics(telemetry)
        risk, reasons = compute_risk(telemetry, metrics, MissionPhase.CRUISE)
        assert risk >= 0.35

    def test_risk_clamped_to_one(self):
        """Multiple risk factors → score clamped to 1.0."""
        telemetry = make_telemetry(
            battery_percent=5.0,
            gps_fix="NO_FIX",
            roll_deg=30.0,
            pitch_deg=30.0,
            health_flags={
                "is_gyrometer_calibration_ok": False,
                "is_accelerometer_calibration_ok": True,
                "is_magnetometer_calibration_ok": True,
                "is_home_position_ok": True,
                "is_global_position_ok": True,
            },
        )
        metrics = extract_metrics(telemetry)
        risk, reasons = compute_risk(telemetry, metrics, MissionPhase.CRUISE)
        assert risk <= 1.0
        assert risk >= 0.8  # Should be very high

    def test_empty_telemetry_no_crash(self):
        """Empty telemetry dict → bounded risk, no crash."""
        telemetry: dict = {}
        metrics = extract_metrics(telemetry)
        risk, reasons = compute_risk(telemetry, metrics, MissionPhase.UNKNOWN)
        assert 0.0 <= risk <= 1.0
        assert len(reasons) > 0  # Should report missing fields

    def test_missing_all_fields_risk(self):
        """All telemetry fields missing → risk from missing fields."""
        telemetry: dict = {"flight_mode": "MISSION"}
        metrics = extract_metrics(telemetry)
        risk, reasons = compute_risk(telemetry, metrics, MissionPhase.CRUISE)
        assert risk > 0.0
        assert any("missing" in r.lower() for r in reasons)
