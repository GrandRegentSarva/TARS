"""
Phase 7 Mapper Tests
=====================
Tests for pure normalization, deterministic ID generation,
and graph-write input mapping.

All tests are pure (no I/O) and independently runnable.
"""

from __future__ import annotations

import pytest

from tars.phase7.mapper import (
    build_mission_projection,
    generate_deterministic_id,
    generate_outcome_id_from_mission,
    map_all_reasoning,
    map_incident,
    map_incidents,
    map_mission,
    map_mission_outcome,
    map_reasoning,
    normalize_text,
    _mission_result_to_outcome_status,
)

from .conftest import (
    make_battery_incident,
    make_incident,
    make_mission,
    make_failed_mission,
    make_reasoning,
)


# =============================================================================
# Text Normalization Tests
# =============================================================================

class TestNormalizeText:
    """Test deterministic text normalization."""

    def test_basic_normalization(self):
        assert normalize_text("GPS Interference") == "gps interference"

    def test_strips_whitespace(self):
        assert normalize_text("  hello  ") == "hello"

    def test_collapses_internal_whitespace(self):
        assert normalize_text("gps   interference   detected") == "gps interference detected"

    def test_handles_tabs_and_newlines(self):
        assert normalize_text("gps\tinterference\ndetected") == "gps interference detected"

    def test_lowercase(self):
        assert normalize_text("GPS INTERFERENCE") == "gps interference"

    def test_empty_string(self):
        assert normalize_text("") == ""

    def test_single_word(self):
        assert normalize_text("interference") == "interference"

    def test_idempotent(self):
        text = "  GPS   Interference  "
        first = normalize_text(text)
        second = normalize_text(first)
        assert first == second


# =============================================================================
# Deterministic ID Generation Tests
# =============================================================================

class TestGenerateDeterministicId:
    """Test stable ID generation from normalized text."""

    def test_stable_id(self):
        id1 = generate_deterministic_id("rc", "gps interference")
        id2 = generate_deterministic_id("rc", "gps interference")
        assert id1 == id2

    def test_prefix_included(self):
        result = generate_deterministic_id("rc", "gps interference")
        assert result.startswith("rc_")

    def test_different_text_different_id(self):
        id1 = generate_deterministic_id("rc", "gps interference")
        id2 = generate_deterministic_id("rc", "battery degradation")
        assert id1 != id2

    def test_different_prefix_different_id(self):
        id1 = generate_deterministic_id("rc", "gps interference")
        id2 = generate_deterministic_id("mit", "gps interference")
        assert id1 != id2

    def test_id_length(self):
        result = generate_deterministic_id("rc", "test")
        # prefix + underscore + 16 hex chars
        assert len(result) == len("rc_") + 16


class TestGenerateOutcomeIdFromMission:
    """Test deterministic outcome ID for mission results."""

    def test_stable_id(self):
        id1 = generate_outcome_id_from_mission("m1", "success")
        id2 = generate_outcome_id_from_mission("m1", "success")
        assert id1 == id2

    def test_different_result_different_id(self):
        id1 = generate_outcome_id_from_mission("m1", "success")
        id2 = generate_outcome_id_from_mission("m1", "failed")
        assert id1 != id2

    def test_prefix(self):
        result = generate_outcome_id_from_mission("m1", "success")
        assert result.startswith("outcome_mission_")


# =============================================================================
# Mission Mapping Tests
# =============================================================================

class TestMapMission:
    """Test Phase 2 mission mapping."""

    def test_maps_required_fields(self):
        mission_data = make_mission()
        record = map_mission(mission_data)
        assert record.mission_id == "mission_test_001"
        assert record.drone_id == "tars-sim-01"
        assert record.mission_result == "success"
        assert record.source_phase == "phase2"

    def test_maps_timestamps(self):
        mission_data = make_mission()
        record = map_mission(mission_data)
        assert record.start_time is not None
        assert record.end_time is not None

    def test_missing_required_field_raises(self):
        data = make_mission()
        del data["mission_id"]
        with pytest.raises(ValueError, match="Missing required fields"):
            map_mission(data)

    def test_none_required_field_raises(self):
        data = make_mission()
        data["drone_id"] = None
        with pytest.raises(ValueError, match="Missing required fields"):
            map_mission(data)


class TestMapMissionOutcome:
    """Test mission result to outcome mapping."""

    def test_success_maps_to_recovered(self):
        data = make_mission(mission_result="success")
        outcome = map_mission_outcome(data)
        assert outcome is not None
        assert outcome.status == "recovered"
        assert outcome.scope == "mission"
        assert outcome.source == "phase2_mission_result"

    def test_failed_maps_to_failed(self):
        data = make_mission(mission_result="failed")
        outcome = map_mission_outcome(data)
        assert outcome is not None
        assert outcome.status == "failed"

    def test_unknown_result_maps_to_unknown(self):
        data = make_mission(mission_result="weird_result")
        outcome = map_mission_outcome(data)
        assert outcome is not None
        assert outcome.status == "unknown"

    def test_no_result_returns_none(self):
        data = make_mission()
        data["mission_result"] = ""
        # Empty string is falsy
        outcome = map_mission_outcome(data)
        assert outcome is None


class TestMissionResultToOutcomeStatus:
    """Test the mission result to outcome status mapping."""

    def test_known_mappings(self):
        assert _mission_result_to_outcome_status("success") == "recovered"
        assert _mission_result_to_outcome_status("completed") == "recovered"
        assert _mission_result_to_outcome_status("nominal") == "recovered"
        assert _mission_result_to_outcome_status("partial") == "degraded"
        assert _mission_result_to_outcome_status("degraded") == "degraded"
        assert _mission_result_to_outcome_status("failed") == "failed"
        assert _mission_result_to_outcome_status("failure") == "failed"
        assert _mission_result_to_outcome_status("aborted") == "failed"
        assert _mission_result_to_outcome_status("crash") == "failed"

    def test_case_insensitive(self):
        assert _mission_result_to_outcome_status("SUCCESS") == "recovered"
        assert _mission_result_to_outcome_status("Failed") == "failed"

    def test_unknown_maps_to_unknown(self):
        assert _mission_result_to_outcome_status("something_else") == "unknown"


# =============================================================================
# Incident Mapping Tests
# =============================================================================

class TestMapIncident:
    """Test Phase 4 incident mapping."""

    def test_maps_required_fields(self):
        data = make_incident()
        record = map_incident(data)
        assert record.incident_id == "inc_test_001"
        assert record.mission_id == "mission_test_001"
        assert record.incident_type == "navigation_instability"
        assert record.severity == "high"
        assert record.source_phase == "phase4"

    def test_maps_optional_fields(self):
        data = make_incident(
            phases=["takeoff", "cruise"],
            evidence=["GPS degraded"],
        )
        record = map_incident(data)
        assert record.phases == ["takeoff", "cruise"]
        assert record.evidence == ["GPS degraded"]

    def test_missing_required_field_raises(self):
        data = make_incident()
        del data["incident_type"]
        with pytest.raises(ValueError, match="Missing required fields"):
            map_incident(data)


class TestMapIncidents:
    """Test batch incident mapping."""

    def test_maps_multiple(self):
        incidents = [make_incident(), make_battery_incident()]
        records = map_incidents(incidents)
        assert len(records) == 2
        assert records[0].incident_type == "navigation_instability"
        assert records[1].incident_type == "battery_degradation"

    def test_empty_list(self):
        assert map_incidents([]) == []


# =============================================================================
# Reasoning Mapping Tests
# =============================================================================

class TestMapReasoning:
    """Test Phase 5 reasoning mapping."""

    def test_produces_four_records(self):
        data = make_reasoning()
        rc, mit, analysis, rec = map_reasoning(data)
        assert rc.root_cause_id.startswith("rc_")
        assert mit.mitigation_id.startswith("mit_")
        assert analysis.reasoning_id == "reason_test_001"
        assert rec.reasoning_id == "reason_test_001"

    def test_root_cause_normalized(self):
        data = make_reasoning(root_cause="  GPS  Interference  ")
        rc, _, _, _ = map_reasoning(data)
        assert rc.normalized_classification == "gps interference"
        assert rc.classification == "  GPS  Interference  "

    def test_mitigation_normalized(self):
        data = make_reasoning(recommendation="  Switch to Visual Odometry  ")
        _, mit, _, _ = map_reasoning(data)
        assert mit.normalized_description == "switch to visual odometry"

    def test_advisory_only_preserved(self):
        data = make_reasoning()
        _, mit, _, rec = map_reasoning(data)
        assert mit.advisory_only is True
        assert rec.advisory_only is True

    def test_analysis_provenance(self):
        data = make_reasoning(
            model="gemini-2.5-flash",
            prompt_version="v1.0",
            confidence=0.85,
        )
        _, _, analysis, _ = map_reasoning(data)
        assert analysis.model == "gemini-2.5-flash"
        assert analysis.prompt_version == "v1.0"
        assert analysis.confidence == 0.85

    def test_missing_required_field_raises(self):
        data = make_reasoning()
        del data["root_cause"]
        with pytest.raises(ValueError, match="Missing required fields"):
            map_reasoning(data)


class TestMapAllReasoning:
    """Test batch reasoning mapping with deduplication."""

    def test_deduplicates_root_causes(self):
        # Two reasoning results with the same root cause text
        r1 = make_reasoning(reasoning_id="r1", root_cause="GPS interference")
        r2 = make_reasoning(reasoning_id="r2", root_cause="GPS interference")
        rcs, mits, analyses, recs = map_all_reasoning([r1, r2])
        assert len(rcs) == 1  # Deduplicated
        assert len(analyses) == 2  # Both analyses preserved

    def test_keeps_distinct_root_causes(self):
        r1 = make_reasoning(reasoning_id="r1", root_cause="GPS interference")
        r2 = make_reasoning(reasoning_id="r2", root_cause="Battery failure")
        rcs, _, _, _ = map_all_reasoning([r1, r2])
        assert len(rcs) == 2

    def test_deduplicates_mitigations(self):
        r1 = make_reasoning(reasoning_id="r1", recommendation="Switch to visual odometry")
        r2 = make_reasoning(reasoning_id="r2", recommendation="Switch to visual odometry")
        _, mits, _, _ = map_all_reasoning([r1, r2])
        assert len(mits) == 1

    def test_empty_list(self):
        rcs, mits, analyses, recs = map_all_reasoning([])
        assert rcs == []
        assert mits == []
        assert analyses == []
        assert recs == []


# =============================================================================
# Full Projection Tests
# =============================================================================

class TestBuildMissionProjection:
    """Test complete mission projection building."""

    def test_full_projection(self):
        mission = make_mission()
        incidents = [make_incident()]
        reasoning = [make_reasoning()]

        proj = build_mission_projection(mission, incidents, reasoning)

        assert proj.mission.mission_id == "mission_test_001"
        assert len(proj.incidents) == 1
        assert len(proj.root_causes) == 1
        assert len(proj.mitigations) == 1
        assert len(proj.analyses) == 1
        assert len(proj.recommendations) == 1
        assert proj.mission_outcome is not None

    def test_projection_without_reasoning(self):
        mission = make_mission()
        incidents = [make_incident()]

        proj = build_mission_projection(mission, incidents, None)

        assert proj.mission.mission_id == "mission_test_001"
        assert len(proj.incidents) == 1
        assert len(proj.root_causes) == 0
        assert len(proj.mitigations) == 0
        assert len(proj.analyses) == 0
        assert len(proj.recommendations) == 0

    def test_projection_without_incidents(self):
        mission = make_mission()

        proj = build_mission_projection(mission, [], None)

        assert proj.mission.mission_id == "mission_test_001"
        assert len(proj.incidents) == 0

    def test_mission_outcome_included(self):
        mission = make_mission(mission_result="success")
        proj = build_mission_projection(mission, [], None)
        assert proj.mission_outcome is not None
        assert proj.mission_outcome.scope == "mission"
        assert proj.mission_outcome.status == "recovered"
