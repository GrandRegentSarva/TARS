"""
Risk & Health Assessment
========================
Deterministic rules for computing health status, signal quality,
and risk score from a single telemetry frame.

Risk is a normalized 0.0-1.0 score computed from additive weights.
Health is a categorical assessment (nominal, degraded, critical).
Signal quality describes individual subsystem conditions.

All rules are simple, explainable, and testable without external
dependencies. They are not incident detection -- just state summarization.
"""

from __future__ import annotations

import logging
import math
from typing import Any

from .models import (
    HealthStatus,
    MissionPhase,
    SignalIndicators,
    SignalQuality,
    StateMetrics,
)

logger = logging.getLogger("phase3.risk")


# =============================================================================
# Risk Weights
# =============================================================================

WEIGHT_GPS_MISSING = 0.45
WEIGHT_GPS_LOW_SATS = 0.20
WEIGHT_BATTERY_CRITICAL = 0.40
WEIGHT_BATTERY_LOW = 0.20
WEIGHT_HEALTH_FLAG_FALSE = 0.35
WEIGHT_ATTITUDE_HIGH = 0.20
WEIGHT_VERTICAL_SPEED_HIGH = 0.20
WEIGHT_MISSING_FIELD = 0.10


def extract_metrics(telemetry: dict[str, Any]) -> StateMetrics:
    """
    Extract derived numeric metrics from a telemetry frame.

    Args:
        telemetry: Raw telemetry dict from a replay frame.

    Returns:
        StateMetrics with available values populated.
    """
    metrics = StateMetrics()

    # Position metrics
    position = telemetry.get("position")
    if position is not None:
        metrics.relative_altitude_m = position.get("relative_altitude_m")

    # Velocity → ground speed
    velocity = telemetry.get("velocity")
    if velocity is not None:
        north = velocity.get("north_m_s", 0.0)
        east = velocity.get("east_m_s", 0.0)
        metrics.ground_speed_m_s = math.sqrt(north ** 2 + east ** 2)

    # Battery
    battery = telemetry.get("battery")
    if battery is not None:
        metrics.battery_percent = battery.get("remaining_percent")

    # GPS
    gps = telemetry.get("gps")
    if gps is not None:
        metrics.gps_satellites = gps.get("num_satellites")

    # Attitude
    attitude = telemetry.get("attitude")
    if attitude is not None:
        roll = attitude.get("roll_deg", 0.0)
        pitch = attitude.get("pitch_deg", 0.0)
        metrics.roll_abs_deg = abs(roll)
        metrics.pitch_abs_deg = abs(pitch)

    return metrics


def compute_signals(
    telemetry: dict[str, Any],
    metrics: StateMetrics,
    phase: MissionPhase,
) -> SignalIndicators:
    """
    Compute signal quality indicators for key subsystems.

    Args:
        telemetry: Raw telemetry dict.
        metrics: Pre-extracted numeric metrics.
        phase: Current mission phase.

    Returns:
        SignalIndicators with quality assessments.
    """
    signals = SignalIndicators()

    # GPS quality
    gps = telemetry.get("gps")
    if gps is None:
        signals.gps_quality = SignalQuality.MISSING
    else:
        fix_type = (gps.get("fix_type") or "").upper()
        sats = gps.get("num_satellites", 0)

        if fix_type in ("NO_GPS", "NO_FIX"):
            signals.gps_quality = SignalQuality.MISSING
        elif sats < 6:
            signals.gps_quality = SignalQuality.WEAK
        else:
            signals.gps_quality = SignalQuality.NORMAL

    # Battery level
    if metrics.battery_percent is None:
        signals.battery_level = SignalQuality.MISSING
    elif metrics.battery_percent < 15.0:
        signals.battery_level = SignalQuality.UNSTABLE
    elif metrics.battery_percent < 30.0:
        signals.battery_level = SignalQuality.WEAK
    else:
        signals.battery_level = SignalQuality.NORMAL

    # Altitude stability (based on vertical speed if available)
    velocity = telemetry.get("velocity")
    if velocity is None:
        signals.altitude_stability = SignalQuality.MISSING
    else:
        down_speed = abs(velocity.get("down_m_s", 0.0))
        altitude = metrics.relative_altitude_m or 0.0
        # High vertical speed near ground is unstable
        if down_speed > 3.0 and altitude < 10.0:
            signals.altitude_stability = SignalQuality.UNSTABLE
        elif down_speed > 2.0:
            signals.altitude_stability = SignalQuality.WEAK
        else:
            signals.altitude_stability = SignalQuality.NORMAL

    # Attitude stability
    if metrics.roll_abs_deg is None or metrics.pitch_abs_deg is None:
        signals.attitude_stability = SignalQuality.MISSING
    else:
        max_tilt = max(metrics.roll_abs_deg, metrics.pitch_abs_deg)
        if max_tilt > 30.0:
            signals.attitude_stability = SignalQuality.UNSTABLE
        elif max_tilt > 15.0:
            signals.attitude_stability = SignalQuality.WEAK
        else:
            signals.attitude_stability = SignalQuality.NORMAL

    return signals


def compute_health(
    telemetry: dict[str, Any],
    metrics: StateMetrics,
    phase: MissionPhase,
) -> tuple[HealthStatus, list[str]]:
    """
    Compute overall health status with human-readable reasons.

    Args:
        telemetry: Raw telemetry dict.
        metrics: Pre-extracted numeric metrics.
        phase: Current mission phase.

    Returns:
        Tuple of (HealthStatus, list of reason strings).
    """
    reasons: list[str] = []
    is_in_flight = phase not in (
        MissionPhase.PREFLIGHT,
        MissionPhase.LANDED,
        MissionPhase.UNKNOWN,
    )

    # Check for missing core telemetry
    missing_core = []
    if telemetry.get("position") is None:
        missing_core.append("position")
    if telemetry.get("battery") is None:
        missing_core.append("battery")
    if telemetry.get("gps") is None:
        missing_core.append("gps")

    if missing_core:
        reasons.append(f"missing core telemetry: {', '.join(missing_core)}")
        return HealthStatus.UNKNOWN, reasons

    # Critical checks
    # Battery < 15%
    if metrics.battery_percent is not None and metrics.battery_percent < 15.0:
        reasons.append(f"battery critically low at {metrics.battery_percent:.1f}%")
        return HealthStatus.CRITICAL, reasons

    # GPS fix is NO_GPS or NO_FIX during non-preflight phase
    gps = telemetry.get("gps", {})
    fix_type = (gps.get("fix_type") or "").upper()
    if fix_type in ("NO_GPS", "NO_FIX") and is_in_flight:
        reasons.append(f"GPS fix lost ({fix_type}) during flight")
        return HealthStatus.CRITICAL, reasons

    # Any core health flag false during flight
    health = telemetry.get("health")
    if health is not None and is_in_flight:
        health_flags = [
            ("is_gyrometer_calibration_ok", "gyrometer calibration"),
            ("is_accelerometer_calibration_ok", "accelerometer calibration"),
            ("is_magnetometer_calibration_ok", "magnetometer calibration"),
            ("is_home_position_ok", "home position"),
            ("is_global_position_ok", "global position"),
        ]
        for flag_key, flag_name in health_flags:
            if health.get(flag_key) is False:
                reasons.append(f"{flag_name} check failed during flight")
                return HealthStatus.CRITICAL, reasons

    # Degraded checks
    degraded_reasons: list[str] = []

    # Battery < 30%
    if metrics.battery_percent is not None and metrics.battery_percent < 30.0:
        degraded_reasons.append(
            f"battery low at {metrics.battery_percent:.1f}%"
        )

    # GPS satellites < 6 during flight
    if metrics.gps_satellites is not None and metrics.gps_satellites < 6 and is_in_flight:
        degraded_reasons.append(
            f"GPS satellites below nominal threshold ({metrics.gps_satellites})"
        )

    # Absolute roll or pitch > 20 deg in cruise
    if phase == MissionPhase.CRUISE:
        if metrics.roll_abs_deg is not None and metrics.roll_abs_deg > 20.0:
            degraded_reasons.append(
                f"roll elevated at {metrics.roll_abs_deg:.1f}° while in cruise"
            )
        if metrics.pitch_abs_deg is not None and metrics.pitch_abs_deg > 20.0:
            degraded_reasons.append(
                f"pitch elevated at {metrics.pitch_abs_deg:.1f}° while in cruise"
            )

    if degraded_reasons:
        return HealthStatus.DEGRADED, degraded_reasons

    return HealthStatus.NOMINAL, []


def compute_risk(
    telemetry: dict[str, Any],
    metrics: StateMetrics,
    phase: MissionPhase,
) -> tuple[float, list[str]]:
    """
    Compute a normalized risk score (0.0 to 1.0) with reasons.

    Uses additive weights for each risk signal. The final score
    is clamped to 1.0.

    Args:
        telemetry: Raw telemetry dict.
        metrics: Pre-extracted numeric metrics.
        phase: Current mission phase.

    Returns:
        Tuple of (risk_score, list of contributing reason strings).
    """
    score = 0.0
    reasons: list[str] = []

    # GPS missing / no fix
    gps = telemetry.get("gps")
    if gps is None:
        score += WEIGHT_GPS_MISSING
        reasons.append("GPS telemetry missing")
    else:
        fix_type = (gps.get("fix_type") or "").upper()
        if fix_type in ("NO_GPS", "NO_FIX"):
            score += WEIGHT_GPS_MISSING
            reasons.append(f"GPS fix lost ({fix_type})")
        elif metrics.gps_satellites is not None and metrics.gps_satellites < 6:
            score += WEIGHT_GPS_LOW_SATS
            reasons.append(
                f"GPS satellites below nominal ({metrics.gps_satellites})"
            )

    # Battery
    if metrics.battery_percent is not None:
        if metrics.battery_percent < 15.0:
            score += WEIGHT_BATTERY_CRITICAL
            reasons.append(
                f"battery critically low ({metrics.battery_percent:.1f}%)"
            )
        elif metrics.battery_percent < 30.0:
            score += WEIGHT_BATTERY_LOW
            reasons.append(
                f"battery low ({metrics.battery_percent:.1f}%)"
            )

    # Health flags
    health = telemetry.get("health")
    if health is not None:
        health_flags = [
            "is_gyrometer_calibration_ok",
            "is_accelerometer_calibration_ok",
            "is_magnetometer_calibration_ok",
            "is_home_position_ok",
            "is_global_position_ok",
        ]
        for flag_key in health_flags:
            if health.get(flag_key) is False:
                score += WEIGHT_HEALTH_FLAG_FALSE
                flag_name = flag_key.replace("is_", "").replace("_ok", "").replace("_", " ")
                reasons.append(f"{flag_name} check failed")
                break  # Only count once for health flags

    # Attitude: roll or pitch > 20 deg
    if metrics.roll_abs_deg is not None and metrics.roll_abs_deg > 20.0:
        score += WEIGHT_ATTITUDE_HIGH
        reasons.append(f"roll elevated ({metrics.roll_abs_deg:.1f}°)")
    if metrics.pitch_abs_deg is not None and metrics.pitch_abs_deg > 20.0:
        score += WEIGHT_ATTITUDE_HIGH
        reasons.append(f"pitch elevated ({metrics.pitch_abs_deg:.1f}°)")

    # Vertical speed high near ground
    velocity = telemetry.get("velocity")
    if velocity is not None:
        down_speed = abs(velocity.get("down_m_s", 0.0))
        altitude = metrics.relative_altitude_m or 0.0
        if down_speed > 3.0 and altitude < 10.0:
            score += WEIGHT_VERTICAL_SPEED_HIGH
            reasons.append(
                f"high vertical speed ({down_speed:.1f} m/s) near ground"
            )

    # Missing telemetry fields
    missing_fields = []
    if telemetry.get("position") is None:
        missing_fields.append("position")
    if telemetry.get("velocity") is None:
        missing_fields.append("velocity")
    if telemetry.get("battery") is None:
        missing_fields.append("battery")
    if telemetry.get("attitude") is None:
        missing_fields.append("attitude")
    if telemetry.get("health") is None:
        missing_fields.append("health")

    if missing_fields:
        score += WEIGHT_MISSING_FIELD * len(missing_fields)
        reasons.append(f"missing telemetry: {', '.join(missing_fields)}")

    # Clamp to 1.0
    score = min(score, 1.0)

    return round(score, 4), reasons
