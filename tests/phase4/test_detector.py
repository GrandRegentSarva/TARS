"""
Tests for Phase 4 Incident Detector (Collapser)
=================================================
Tests incident collapsing, persistence thresholds, gap merging,
and deterministic output.
"""

from __future__ import annotations

import pytest

from tars.phase4.detector import detect_incidents
from tars.phase4.models import IncidentType, Severity

from .conftest import (
    make_critical_health_state,
    make_gps_degraded_states,
    make_high_risk_states,
    make_nominal_states,
    make_state,
    make_states,
)


class TestNominalStates:
    """Test that nominal states produce no incidents."""

    def test_no_incidents_from_nominal(self):
        states = make_nominal_states(count=20)
        incidents = detect_incidents(states, "test_mission")
        assert len(incidents) == 0

    def test_no_incidents_from_ground_phases(self):
        states = make_states(10, phase="preflight", health="nominal", risk=0.0)
        incidents = detect_incidents(states, "test_mission")
        assert len(incidents) == 0


class TestPersistenceThreshold:
    """Test minimum state persistence before incident creation."""

    def test_one_weak_gps_no_incident(self):
        """One transient weak GPS state should not produce an incident."""
        states = make_nominal_states(5)
        states[2] = make_state(
            sequence=3, elapsed_ms=3000,
            phase="cruise", gps_quality="weak",
        )
        incidents = detect_incidents(states, "test_mission", min_states=3)
        nav_incidents = [
            i for i in incidents
            if i.incident_type == IncidentType.NAVIGATION_INSTABILITY
        ]
        assert len(nav_incidents) == 0

    def test_two_weak_gps_no_incident(self):
        """Two weak GPS states still below min_states=3."""
        states = make_nominal_states(5)
        states[1] = make_state(
            sequence=2, elapsed_ms=2000,
            phase="cruise", gps_quality="weak",
        )
        states[2] = make_state(
            sequence=3, elapsed_ms=3000,
            phase="cruise", gps_quality="weak",
        )
        incidents = detect_incidents(states, "test_mission", min_states=3)
        nav_incidents = [
            i for i in incidents
            if i.incident_type == IncidentType.NAVIGATION_INSTABILITY
        ]
        assert len(nav_incidents) == 0

    def test_three_weak_gps_creates_incident(self):
        """Three consecutive weak GPS states should create an incident."""
        states = make_gps_degraded_states(count=3)
        incidents = detect_incidents(states, "test_mission", min_states=3)
        nav_incidents = [
            i for i in incidents
            if i.incident_type == IncidentType.NAVIGATION_INSTABILITY
        ]
        assert len(nav_incidents) == 1

    def test_sustained_weak_gps_collapses_into_one(self):
        """Five consecutive weak GPS states should collapse into one incident."""
        states = make_gps_degraded_states(count=5)
        incidents = detect_incidents(states, "test_mission", min_states=3)
        nav_incidents = [
            i for i in incidents
            if i.incident_type == IncidentType.NAVIGATION_INSTABILITY
        ]
        assert len(nav_incidents) == 1
        assert nav_incidents[0].contributing_states == 5


class TestImmediateRules:
    """Test rules that bypass persistence threshold."""

    def test_critical_health_immediate(self):
        """Critical health should produce an incident from a single state."""
        states = make_nominal_states(5)
        states[2] = make_critical_health_state(sequence=3)
        incidents = detect_incidents(states, "test_mission", min_states=3)
        sensor_incidents = [
            i for i in incidents
            if i.incident_type == IncidentType.SENSOR_HEALTH_FAILURE
        ]
        assert len(sensor_incidents) == 1
        assert sensor_incidents[0].severity == Severity.CRITICAL

    def test_high_risk_critical_immediate(self):
        """Risk >= 0.8 should produce an immediate incident."""
        states = make_nominal_states(5)
        states[2] = make_state(
            sequence=3, elapsed_ms=3000,
            phase="cruise", risk=0.85,
        )
        incidents = detect_incidents(states, "test_mission", min_states=3)
        risk_incidents = [
            i for i in incidents
            if i.incident_type == IncidentType.HIGH_RISK_STATE
        ]
        assert len(risk_incidents) == 1
        assert risk_incidents[0].severity == Severity.CRITICAL


class TestGapMerging:
    """Test incident merging based on gap threshold."""

    def test_close_matches_merge(self):
        """Matches within max_gap_ms should merge into one incident."""
        states = []
        # First cluster: seq 1-3 at 1000-3000ms
        states.extend(make_gps_degraded_states(count=3))
        # Gap of 2000ms (within default 5000ms)
        # Second cluster: seq 6-8 at 6000-8000ms
        for i in range(3):
            states.append(make_state(
                sequence=6 + i, elapsed_ms=6000 + i * 1000,
                phase="cruise", gps_quality="weak", health="degraded", risk=0.4,
            ))
        incidents = detect_incidents(
            states, "test_mission", max_gap_ms=5000, min_states=3,
        )
        nav_incidents = [
            i for i in incidents
            if i.incident_type == IncidentType.NAVIGATION_INSTABILITY
        ]
        assert len(nav_incidents) == 1
        assert nav_incidents[0].contributing_states == 6

    def test_distant_matches_split(self):
        """Matches beyond max_gap_ms should produce separate incidents."""
        states = []
        # First cluster: seq 1-3 at 1000-3000ms
        states.extend(make_gps_degraded_states(count=3))
        # Gap of 10000ms (beyond 5000ms threshold)
        # Second cluster: seq 14-16 at 14000-16000ms
        for i in range(3):
            states.append(make_state(
                sequence=14 + i, elapsed_ms=14000 + i * 1000,
                phase="cruise", gps_quality="weak", health="degraded", risk=0.4,
            ))
        incidents = detect_incidents(
            states, "test_mission", max_gap_ms=5000, min_states=3,
        )
        nav_incidents = [
            i for i in incidents
            if i.incident_type == IncidentType.NAVIGATION_INSTABILITY
        ]
        assert len(nav_incidents) == 2


class TestIncidentProperties:
    """Test incident field correctness."""

    def test_peak_severity(self):
        """Incident severity should reflect the peak match severity."""
        states = []
        # Mix of weak and missing GPS
        states.append(make_state(
            sequence=1, elapsed_ms=1000,
            phase="cruise", gps_quality="weak",
        ))
        states.append(make_state(
            sequence=2, elapsed_ms=2000,
            phase="cruise", gps_quality="missing",
        ))
        states.append(make_state(
            sequence=3, elapsed_ms=3000,
            phase="cruise", gps_quality="weak",
        ))
        incidents = detect_incidents(states, "test_mission", min_states=1)
        nav_incidents = [
            i for i in incidents
            if i.incident_type == IncidentType.NAVIGATION_INSTABILITY
        ]
        assert len(nav_incidents) == 1
        assert nav_incidents[0].severity == Severity.HIGH  # From missing GPS

    def test_peak_risk(self):
        """Incident peak_risk should be the maximum risk in the run."""
        states = [
            make_state(sequence=1, elapsed_ms=1000, phase="cruise",
                       gps_quality="weak", risk=0.3),
            make_state(sequence=2, elapsed_ms=2000, phase="cruise",
                       gps_quality="weak", risk=0.7),
            make_state(sequence=3, elapsed_ms=3000, phase="cruise",
                       gps_quality="weak", risk=0.5),
        ]
        incidents = detect_incidents(states, "test_mission", min_states=1)
        nav_incidents = [
            i for i in incidents
            if i.incident_type == IncidentType.NAVIGATION_INSTABILITY
        ]
        assert nav_incidents[0].peak_risk == pytest.approx(0.7)

    def test_phases_collected(self):
        """Incident should collect all unique phases."""
        states = [
            make_state(sequence=1, elapsed_ms=1000, phase="climb",
                       gps_quality="weak"),
            make_state(sequence=2, elapsed_ms=2000, phase="cruise",
                       gps_quality="weak"),
            make_state(sequence=3, elapsed_ms=3000, phase="cruise",
                       gps_quality="weak"),
        ]
        incidents = detect_incidents(states, "test_mission", min_states=1)
        nav_incidents = [
            i for i in incidents
            if i.incident_type == IncidentType.NAVIGATION_INSTABILITY
        ]
        assert "climb" in nav_incidents[0].phases
        assert "cruise" in nav_incidents[0].phases

    def test_evidence_deduplicated(self):
        """Incident evidence should be deduplicated."""
        states = make_gps_degraded_states(count=3, gps_quality="weak")
        incidents = detect_incidents(states, "test_mission", min_states=1)
        nav_incidents = [
            i for i in incidents
            if i.incident_type == IncidentType.NAVIGATION_INSTABILITY
        ]
        evidence = nav_incidents[0].evidence
        assert len(evidence) == len(set(evidence))

    def test_start_end_times(self):
        """Incident start/end should match first/last match."""
        states = make_gps_degraded_states(count=5)
        incidents = detect_incidents(states, "test_mission", min_states=1)
        nav_incidents = [
            i for i in incidents
            if i.incident_type == IncidentType.NAVIGATION_INSTABILITY
        ]
        inc = nav_incidents[0]
        assert inc.start_ms == states[0]["elapsed_ms"]
        assert inc.end_ms == states[-1]["elapsed_ms"]
        assert inc.start_sequence == states[0]["sequence"]
        assert inc.end_sequence == states[-1]["sequence"]

    def test_stable_incident_id(self):
        """Same input should produce the same incident ID."""
        states = make_gps_degraded_states(count=3)
        incidents_1 = detect_incidents(states, "test_mission", min_states=1)
        incidents_2 = detect_incidents(states, "test_mission", min_states=1)
        nav_1 = [i for i in incidents_1 if i.incident_type == IncidentType.NAVIGATION_INSTABILITY]
        nav_2 = [i for i in incidents_2 if i.incident_type == IncidentType.NAVIGATION_INSTABILITY]
        assert nav_1[0].incident_id == nav_2[0].incident_id


class TestDeterminism:
    """Test that detection is deterministic across repeated runs."""

    def test_repeated_detection_same_result(self):
        """Running detection twice on the same data should produce identical results."""
        states = make_high_risk_states(count=5, risk=0.85)
        incidents_1 = detect_incidents(states, "test_mission")
        incidents_2 = detect_incidents(states, "test_mission")
        assert len(incidents_1) == len(incidents_2)
        for i1, i2 in zip(incidents_1, incidents_2):
            assert i1.incident_id == i2.incident_id
            assert i1.incident_type == i2.incident_type
            assert i1.severity == i2.severity
            assert i1.contributing_states == i2.contributing_states


class TestMultipleIncidentTypes:
    """Test detection of multiple incident types from the same states."""

    def test_gps_and_risk_incidents(self):
        """States with GPS degradation and high risk should produce both types."""
        states = make_states(
            5,
            phase="cruise",
            health="degraded",
            risk=0.85,
            gps_quality="missing",
        )
        incidents = detect_incidents(states, "test_mission", min_states=1)
        types = {i.incident_type for i in incidents}
        assert IncidentType.NAVIGATION_INSTABILITY in types
        assert IncidentType.HIGH_RISK_STATE in types

    def test_ordered_by_start_ms(self):
        """Incidents should be ordered by start_ms."""
        states = make_states(
            5,
            phase="cruise",
            health="degraded",
            risk=0.85,
            gps_quality="missing",
        )
        incidents = detect_incidents(states, "test_mission", min_states=1)
        for i in range(1, len(incidents)):
            assert incidents[i].start_ms >= incidents[i - 1].start_ms


class TestStatisticalDetection:
    """Test that statistical detectors are integrated into detect_incidents."""

    def test_battery_drop_rate_adds_evidence(self):
        """Fast battery drain should produce battery_degradation evidence."""
        states = []
        for i in range(5):
            states.append(make_state(
                sequence=i + 1,
                elapsed_ms=(i + 1) * 1000,
                phase="cruise",
                battery_level="weak",
                battery_percent=90.0 - i * 10.0,  # 90, 80, 70, 60, 50
            ))
        incidents = detect_incidents(states, "test_mission", min_states=1)
        battery_incidents = [
            inc for inc in incidents
            if inc.incident_type == IncidentType.BATTERY_DEGRADATION
        ]
        assert len(battery_incidents) >= 1
        # Should have statistical evidence about drop rate
        all_evidence = []
        for inc in battery_incidents:
            all_evidence.extend(inc.evidence)
        assert any("dropping" in e.lower() or "%/s" in e for e in all_evidence)

    def test_altitude_oscillation_adds_evidence(self):
        """Altitude oscillation should enrich altitude_instability incidents."""
        states = []
        for i in range(12):
            alt = 20.0 + (5.0 if i % 2 == 0 else -5.0)
            states.append(make_state(
                sequence=i + 1,
                elapsed_ms=(i + 1) * 1000,
                phase="cruise",
                altitude_stability="unstable",
                relative_altitude_m=alt,
            ))
        incidents = detect_incidents(states, "test_mission", min_states=1)
        alt_incidents = [
            inc for inc in incidents
            if inc.incident_type == IncidentType.ALTITUDE_INSTABILITY
        ]
        assert len(alt_incidents) >= 1
        all_evidence = []
        for inc in alt_incidents:
            all_evidence.extend(inc.evidence)
        assert any("oscillat" in e.lower() for e in all_evidence)

    def test_sustained_risk_adds_evidence(self):
        """Sustained elevated risk should enrich high_risk_state incidents."""
        states = make_states(
            10,
            phase="cruise",
            health="degraded",
            risk=0.75,
            gps_quality="weak",
        )
        incidents = detect_incidents(states, "test_mission", min_states=1)
        risk_incidents = [
            inc for inc in incidents
            if inc.incident_type == IncidentType.HIGH_RISK_STATE
        ]
        assert len(risk_incidents) >= 1
        all_evidence = []
        for inc in risk_incidents:
            all_evidence.extend(inc.evidence)
        assert any("rolling" in e.lower() or "sustained" in e.lower() or "mean" in e.lower() for e in all_evidence)

    def test_nominal_states_no_statistical_incidents(self):
        """Nominal states should not produce statistical incidents."""
        states = make_nominal_states(count=20)
        incidents = detect_incidents(states, "test_mission")
        assert len(incidents) == 0
