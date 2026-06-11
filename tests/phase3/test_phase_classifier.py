"""
Phase Classifier Tests
======================
Tests for deterministic mission phase classification.

Coverage:
- Unknown phase when position or flight mode is missing
- Preflight when HOLD mode and low altitude
- Takeoff when altitude rising from < 2m
- Climb when altitude rising below cruise band
- Cruise when altitude >= 10m in MISSION mode
- Return to launch when RTL or RETURN mode
- Landing when altitude decreasing below 10m
- Landed when altitude < 0.5m
"""

from __future__ import annotations

import pytest

from tars.phase3.models import MissionPhase
from tars.phase3.phase_classifier import classify_phase

from .conftest import make_telemetry


class TestClassifyPhase:
    """Test mission phase classification rules."""

    def test_unknown_when_no_position(self):
        """Missing position → unknown."""
        telemetry = make_telemetry()
        del telemetry["position"]
        assert classify_phase(telemetry) == MissionPhase.UNKNOWN

    def test_unknown_when_no_flight_mode(self):
        """Missing flight mode → unknown."""
        telemetry = make_telemetry()
        telemetry["flight_mode"] = ""
        assert classify_phase(telemetry) == MissionPhase.UNKNOWN

    def test_unknown_when_flight_mode_none(self):
        """None flight mode → unknown."""
        telemetry = make_telemetry()
        telemetry["flight_mode"] = None
        assert classify_phase(telemetry) == MissionPhase.UNKNOWN

    def test_unknown_when_no_altitude(self):
        """Missing relative_altitude_m → unknown."""
        telemetry = make_telemetry()
        del telemetry["position"]["relative_altitude_m"]
        assert classify_phase(telemetry) == MissionPhase.UNKNOWN

    def test_landed_low_altitude(self):
        """Altitude < 0.5m in non-HOLD mode → landed."""
        telemetry = make_telemetry(altitude=0.3, flight_mode="MISSION")
        assert classify_phase(telemetry) == MissionPhase.LANDED

    def test_preflight_hold_low_altitude(self):
        """HOLD mode + altitude < 1m → preflight."""
        telemetry = make_telemetry(altitude=0.8, flight_mode="HOLD")
        assert classify_phase(telemetry) == MissionPhase.PREFLIGHT

    def test_preflight_hold_at_ground_level(self):
        """HOLD mode at altitude < 0.5m → preflight (not landed)."""
        telemetry = make_telemetry(altitude=0.3, flight_mode="HOLD")
        assert classify_phase(telemetry) == MissionPhase.PREFLIGHT

    def test_return_to_launch_rtl(self):
        """RTL flight mode → return_to_launch."""
        telemetry = make_telemetry(altitude=15.0, flight_mode="RTL")
        assert classify_phase(telemetry) == MissionPhase.RETURN_TO_LAUNCH

    def test_return_to_launch_return(self):
        """RETURN flight mode → return_to_launch."""
        telemetry = make_telemetry(altitude=15.0, flight_mode="RETURN")
        assert classify_phase(telemetry) == MissionPhase.RETURN_TO_LAUNCH

    def test_takeoff_rising_from_low(self):
        """Altitude rising from < 2m → takeoff."""
        telemetry = make_telemetry(altitude=3.0, flight_mode="MISSION")
        assert classify_phase(telemetry, prev_altitude=1.0) == MissionPhase.TAKEOFF

    def test_cruise_high_altitude_mission_mode(self):
        """Altitude >= 10m + MISSION mode → cruise."""
        telemetry = make_telemetry(altitude=20.0, flight_mode="MISSION")
        assert classify_phase(telemetry) == MissionPhase.CRUISE

    def test_cruise_high_altitude_other_mode(self):
        """Altitude >= 10m in non-MISSION mode → cruise (fallback)."""
        telemetry = make_telemetry(altitude=15.0, flight_mode="OFFBOARD")
        assert classify_phase(telemetry) == MissionPhase.CRUISE

    def test_climb_rising_below_cruise(self):
        """Altitude rising below 10m → climb."""
        telemetry = make_telemetry(altitude=7.0, flight_mode="MISSION")
        assert classify_phase(telemetry, prev_altitude=5.0) == MissionPhase.CLIMB

    def test_landing_descending_low(self):
        """Altitude decreasing below 10m → landing."""
        telemetry = make_telemetry(altitude=5.0, flight_mode="MISSION")
        assert classify_phase(telemetry, prev_altitude=8.0) == MissionPhase.LANDING

    def test_no_prev_altitude_high(self):
        """No previous altitude + high altitude → cruise."""
        telemetry = make_telemetry(altitude=20.0, flight_mode="MISSION")
        assert classify_phase(telemetry, prev_altitude=None) == MissionPhase.CRUISE
