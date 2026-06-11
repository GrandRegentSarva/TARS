"""
Mission Phase Classifier
========================
Deterministic rules for classifying the current mission phase
from a single telemetry frame.

Phase classification is based on:
- Flight mode string (HOLD, MISSION, RETURN, RTL, etc.)
- Relative altitude
- Altitude trend (rising/falling)

Rules are intentionally simple and explainable. They are not
incident detection -- just operational state summarization.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from .models import MissionPhase

logger = logging.getLogger("phase3.phase_classifier")


def classify_phase(
    telemetry: dict[str, Any],
    prev_altitude: Optional[float] = None,
) -> MissionPhase:
    """
    Classify the current mission phase from a telemetry frame.

    Args:
        telemetry: Raw telemetry dict from a replay frame.
        prev_altitude: Previous frame's relative altitude (for trend detection).

    Returns:
        The classified MissionPhase.
    """
    position = telemetry.get("position")
    flight_mode = telemetry.get("flight_mode") or ""
    flight_mode_upper = flight_mode.upper()

    # No position or no flight mode → unknown
    if position is None or not flight_mode:
        return MissionPhase.UNKNOWN

    altitude = position.get("relative_altitude_m")
    if altitude is None:
        return MissionPhase.UNKNOWN

    # Determine altitude trend
    altitude_rising = False
    altitude_falling = False
    if prev_altitude is not None:
        delta = altitude - prev_altitude
        if delta > 0.3:
            altitude_rising = True
        elif delta < -0.3:
            altitude_falling = True

    # Rule: preflight -- HOLD mode and altitude < 1m (checked before landed
    # so a stationary drone in HOLD at ground level is correctly classified)
    if "HOLD" in flight_mode_upper and altitude < 1.0:
        return MissionPhase.PREFLIGHT

    # Rule: landed -- altitude < 0.5m
    if altitude < 0.5:
        return MissionPhase.LANDED

    # Rule: return_to_launch -- flight mode contains RETURN or RTL
    if "RETURN" in flight_mode_upper or "RTL" in flight_mode_upper:
        return MissionPhase.RETURN_TO_LAUNCH

    # Rule: takeoff -- altitude rising from < 2m to >= 2m
    if altitude_rising and altitude < 5.0 and (prev_altitude is not None and prev_altitude < 2.0):
        return MissionPhase.TAKEOFF

    # Rule: landing -- altitude decreasing and altitude < 10m
    if altitude_falling and altitude < 10.0:
        return MissionPhase.LANDING

    # Rule: cruise -- altitude >= 10m and flight mode contains MISSION
    if altitude >= 10.0 and "MISSION" in flight_mode_upper:
        return MissionPhase.CRUISE

    # Rule: climb -- altitude rising and altitude < cruise band (10m)
    if altitude_rising and altitude < 10.0:
        return MissionPhase.CLIMB

    # Rule: cruise fallback -- altitude >= 10m in any active flight mode
    if altitude >= 10.0:
        return MissionPhase.CRUISE

    # Default
    return MissionPhase.UNKNOWN
