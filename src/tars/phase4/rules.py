"""
Deterministic Rule Evaluator
=============================
Evaluates individual Phase 3 state snapshots against deterministic rules.

Each rule function:
- Accepts a single state dict (matching Phase 3 StateSnapshot)
- Returns a list of RuleMatch objects (zero or more)
- Is pure: no Redis, HTTP, or database access
- Is independently unit-testable

The evaluate_state() function runs all rules against a state and returns
the combined list of matches.
"""

from __future__ import annotations

from .config import settings
from .models import IncidentType, RuleMatch, Severity


# =============================================================================
# Flight phase helpers
# =============================================================================

_GROUND_PHASES = {"preflight", "landed", "unknown"}


def _is_in_flight(phase: str) -> bool:
    """Return True if the phase represents active flight."""
    return phase not in _GROUND_PHASES


# =============================================================================
# Individual Rule Functions
# =============================================================================

def check_navigation_instability(state: dict) -> list[RuleMatch]:
    """
    Navigation instability rule.

    Triggers when GPS quality is degraded during flight:
    - GPS weak/unstable/missing during flight
    - GPS degraded + risk >= 0.5
    - GPS degraded + attitude or altitude also degraded
    """
    matches: list[RuleMatch] = []
    phase = state.get("phase", "unknown")
    if not _is_in_flight(phase):
        return matches

    signals = state.get("signals", {})
    gps = signals.get("gps_quality", "normal")
    risk = state.get("risk", 0.0)

    if gps in ("weak", "unstable", "missing"):
        evidence: list[str] = []
        severity = Severity.LOW

        if gps == "missing":
            evidence.append("GPS signal missing during flight")
            severity = Severity.HIGH
        elif gps == "unstable":
            evidence.append("GPS signal unstable during flight")
            severity = Severity.MEDIUM
        else:
            evidence.append("GPS signal weak during flight")

        # Escalate if risk is also elevated
        if risk >= settings.INCIDENT_ELEVATED_RISK:
            evidence.append(f"Risk elevated at {risk:.2f}")
            if severity == Severity.LOW:
                severity = Severity.MEDIUM

        # Escalate if attitude or altitude also degraded
        attitude = signals.get("attitude_stability", "normal")
        altitude = signals.get("altitude_stability", "normal")
        if attitude in ("weak", "unstable"):
            evidence.append(f"Attitude stability {attitude} during GPS degradation")
            if severity.value in ("low", "medium"):
                severity = Severity.HIGH
        if altitude in ("weak", "unstable"):
            evidence.append(f"Altitude stability {altitude} during GPS degradation")
            if severity.value in ("low", "medium"):
                severity = Severity.HIGH

        matches.append(RuleMatch(
            incident_type=IncidentType.NAVIGATION_INSTABILITY,
            severity=severity,
            sequence=state.get("sequence", 0),
            elapsed_ms=state.get("elapsed_ms", 0),
            phase=phase,
            evidence=evidence,
            risk=risk,
        ))

    return matches


def check_battery_degradation(state: dict) -> list[RuleMatch]:
    """
    Battery degradation rule.

    Triggers when:
    - Battery signal is weak (needs persistence check in detector)
    - Battery signal is unstable (immediate)
    """
    matches: list[RuleMatch] = []
    signals = state.get("signals", {})
    battery = signals.get("battery_level", "normal")

    if battery in ("weak", "unstable"):
        evidence: list[str] = []
        severity = Severity.LOW

        if battery == "unstable":
            evidence.append("Battery level unstable")
            severity = Severity.HIGH
        else:
            evidence.append("Battery level weak")
            severity = Severity.MEDIUM

        metrics = state.get("metrics", {})
        pct = metrics.get("battery_percent")
        if pct is not None:
            evidence.append(f"Battery at {pct:.1f}%")
            if pct < 15.0:
                severity = Severity.CRITICAL

        matches.append(RuleMatch(
            incident_type=IncidentType.BATTERY_DEGRADATION,
            severity=severity,
            sequence=state.get("sequence", 0),
            elapsed_ms=state.get("elapsed_ms", 0),
            phase=state.get("phase", "unknown"),
            evidence=evidence,
            risk=state.get("risk", 0.0),
        ))

    return matches


def check_attitude_instability(state: dict) -> list[RuleMatch]:
    """
    Attitude instability rule.

    Triggers when attitude stability is weak/unstable during cruise.
    """
    matches: list[RuleMatch] = []
    phase = state.get("phase", "unknown")
    signals = state.get("signals", {})
    attitude = signals.get("attitude_stability", "normal")

    if attitude in ("weak", "unstable") and _is_in_flight(phase):
        evidence: list[str] = []
        severity = Severity.LOW

        if attitude == "unstable":
            evidence.append(f"Attitude unstable during {phase}")
            severity = Severity.HIGH
        else:
            evidence.append(f"Attitude weak during {phase}")
            severity = Severity.MEDIUM

        metrics = state.get("metrics", {})
        roll = metrics.get("roll_abs_deg")
        pitch = metrics.get("pitch_abs_deg")
        if roll is not None and roll > 25.0:
            evidence.append(f"Roll angle {roll:.1f}° exceeds threshold")
        if pitch is not None and pitch > 25.0:
            evidence.append(f"Pitch angle {pitch:.1f}° exceeds threshold")

        matches.append(RuleMatch(
            incident_type=IncidentType.ATTITUDE_INSTABILITY,
            severity=severity,
            sequence=state.get("sequence", 0),
            elapsed_ms=state.get("elapsed_ms", 0),
            phase=phase,
            evidence=evidence,
            risk=state.get("risk", 0.0),
        ))

    return matches


def check_altitude_instability(state: dict) -> list[RuleMatch]:
    """
    Altitude instability rule.

    Triggers when altitude stability is unstable.
    """
    matches: list[RuleMatch] = []
    signals = state.get("signals", {})
    altitude = signals.get("altitude_stability", "normal")

    if altitude == "unstable":
        phase = state.get("phase", "unknown")
        evidence = [f"Altitude unstable during {phase}"]
        severity = Severity.MEDIUM

        metrics = state.get("metrics", {})
        alt = metrics.get("relative_altitude_m")
        if alt is not None and alt < 5.0 and _is_in_flight(phase):
            evidence.append(f"Altitude instability near ground ({alt:.1f}m)")
            severity = Severity.HIGH

        matches.append(RuleMatch(
            incident_type=IncidentType.ALTITUDE_INSTABILITY,
            severity=severity,
            sequence=state.get("sequence", 0),
            elapsed_ms=state.get("elapsed_ms", 0),
            phase=phase,
            evidence=evidence,
            risk=state.get("risk", 0.0),
        ))

    return matches


def check_sensor_health_failure(state: dict) -> list[RuleMatch]:
    """
    Sensor health failure rule.

    Triggers immediately when:
    - Phase 3 health is critical
    - At least one reason indicates a sensor or position failure

    Does NOT trigger for battery-only critical states -- those are
    handled by check_battery_degradation().
    """
    matches: list[RuleMatch] = []
    health = state.get("health", "unknown")

    if health == "critical":
        reasons = state.get("reasons", [])

        # Keywords that indicate sensor / position failures
        _SENSOR_KEYWORDS = (
            "position", "gps", "magnetometer", "accelerometer",
            "gyrometer", "gyroscope", "barometer", "imu", "sensor",
            "calibration",
        )
        _FAILURE_KEYWORDS = ("fail", "not ok", "missing", "error", "lost")

        sensor_evidence: list[str] = []
        for reason in reasons:
            r_lower = reason.lower()
            has_sensor = any(kw in r_lower for kw in _SENSOR_KEYWORDS)
            has_failure = any(kw in r_lower for kw in _FAILURE_KEYWORDS)
            if has_sensor and has_failure:
                sensor_evidence.append(reason)
            elif has_sensor:
                # Sensor mentioned without explicit failure keyword --
                # still counts (e.g. "Global position not ok")
                sensor_evidence.append(reason)

        # Only emit if at least one reason is sensor/position related
        if sensor_evidence:
            evidence = ["Health status critical"] + sensor_evidence
            matches.append(RuleMatch(
                incident_type=IncidentType.SENSOR_HEALTH_FAILURE,
                severity=Severity.CRITICAL,
                sequence=state.get("sequence", 0),
                elapsed_ms=state.get("elapsed_ms", 0),
                phase=state.get("phase", "unknown"),
                evidence=evidence,
                risk=state.get("risk", 0.0),
            ))

    return matches


def check_telemetry_degradation(state: dict) -> list[RuleMatch]:
    """
    Telemetry degradation rule.

    Triggers when:
    - Two or more signals are missing
    - Health is unknown during active flight
    """
    matches: list[RuleMatch] = []
    signals = state.get("signals", {})
    health = state.get("health", "unknown")
    phase = state.get("phase", "unknown")

    missing_count = sum(
        1 for v in signals.values() if v == "missing"
    )

    if missing_count >= 2:
        evidence = [f"{missing_count} signal(s) missing"]
        for sig_name, sig_val in signals.items():
            if sig_val == "missing":
                evidence.append(f"{sig_name} signal missing")

        matches.append(RuleMatch(
            incident_type=IncidentType.TELEMETRY_DEGRADATION,
            severity=Severity.HIGH,
            sequence=state.get("sequence", 0),
            elapsed_ms=state.get("elapsed_ms", 0),
            phase=phase,
            evidence=evidence,
            risk=state.get("risk", 0.0),
        ))

    elif health == "unknown" and _is_in_flight(phase):
        matches.append(RuleMatch(
            incident_type=IncidentType.TELEMETRY_DEGRADATION,
            severity=Severity.MEDIUM,
            sequence=state.get("sequence", 0),
            elapsed_ms=state.get("elapsed_ms", 0),
            phase=phase,
            evidence=["Health unknown during active flight"],
            risk=state.get("risk", 0.0),
        ))

    return matches


def check_high_risk_state(state: dict) -> list[RuleMatch]:
    """
    High-risk state rule.

    Triggers immediately when:
    - Risk reaches INCIDENT_HIGH_RISK (0.8)
    - Risk above INCIDENT_ELEVATED_RISK (0.6) needs persistence (handled by detector)
    """
    matches: list[RuleMatch] = []
    risk = state.get("risk", 0.0)

    if risk >= settings.INCIDENT_HIGH_RISK:
        matches.append(RuleMatch(
            incident_type=IncidentType.HIGH_RISK_STATE,
            severity=Severity.CRITICAL,
            sequence=state.get("sequence", 0),
            elapsed_ms=state.get("elapsed_ms", 0),
            phase=state.get("phase", "unknown"),
            evidence=[f"Risk score {risk:.2f} exceeds high threshold ({settings.INCIDENT_HIGH_RISK})"],
            risk=risk,
        ))
    elif risk >= settings.INCIDENT_ELEVATED_RISK:
        matches.append(RuleMatch(
            incident_type=IncidentType.HIGH_RISK_STATE,
            severity=Severity.HIGH,
            sequence=state.get("sequence", 0),
            elapsed_ms=state.get("elapsed_ms", 0),
            phase=state.get("phase", "unknown"),
            evidence=[f"Risk score {risk:.2f} above elevated threshold ({settings.INCIDENT_ELEVATED_RISK})"],
            risk=risk,
        ))

    return matches


# =============================================================================
# Combined Evaluator
# =============================================================================

_ALL_RULES = [
    check_navigation_instability,
    check_battery_degradation,
    check_attitude_instability,
    check_altitude_instability,
    check_sensor_health_failure,
    check_telemetry_degradation,
    check_high_risk_state,
]


def evaluate_state(state: dict) -> list[RuleMatch]:
    """
    Run all deterministic rules against a single state snapshot.

    Args:
        state: A dict matching Phase 3 StateSnapshot structure.

    Returns:
        Combined list of RuleMatch objects from all triggered rules.
    """
    matches: list[RuleMatch] = []
    for rule_fn in _ALL_RULES:
        matches.extend(rule_fn(state))
    return matches
