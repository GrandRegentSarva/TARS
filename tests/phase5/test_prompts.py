"""
Tests for Phase 5 Reasoning Prompts
=====================================
Tests prompt construction, versioning, and content constraints.
"""

from __future__ import annotations

import json

from tars.phase5.prompts import (
    PROMPT_VERSION,
    SYSTEM_INSTRUCTION,
    build_incident_prompt,
)

from .conftest import make_incident, make_battery_incident, make_minimal_incident


# =============================================================================
# System Instruction Tests
# =============================================================================

class TestSystemInstruction:
    """Test system instruction content."""

    def test_contains_advisory_role(self):
        assert "advisory" in SYSTEM_INSTRUCTION.lower()

    def test_contains_evidence_grounding(self):
        assert "evidence" in SYSTEM_INSTRUCTION.lower()

    def test_contains_no_flight_commands(self):
        assert "never" in SYSTEM_INSTRUCTION.lower()
        assert "execute" in SYSTEM_INSTRUCTION.lower()

    def test_contains_confidence_guidance(self):
        assert "confidence" in SYSTEM_INSTRUCTION.lower()

    def test_contains_uncertainties_guidance(self):
        assert "uncertainties" in SYSTEM_INSTRUCTION.lower()

    def test_contains_json_output_format(self):
        assert "json" in SYSTEM_INSTRUCTION.lower()


# =============================================================================
# Prompt Builder Tests
# =============================================================================

class TestBuildIncidentPrompt:
    """Test incident prompt construction."""

    def test_includes_prompt_version(self):
        incident = make_incident()
        prompt = build_incident_prompt(incident)
        assert PROMPT_VERSION in prompt

    def test_includes_incident_type(self):
        incident = make_incident(incident_type="navigation_instability")
        prompt = build_incident_prompt(incident)
        assert "navigation_instability" in prompt

    def test_includes_severity(self):
        incident = make_incident(severity="high")
        prompt = build_incident_prompt(incident)
        assert "high" in prompt

    def test_includes_timing(self):
        incident = make_incident(start_ms=5000, end_ms=10000)
        prompt = build_incident_prompt(incident)
        assert "5000" in prompt
        assert "10000" in prompt

    def test_includes_peak_risk(self):
        incident = make_incident(peak_risk=0.78)
        prompt = build_incident_prompt(incident)
        assert "0.78" in prompt

    def test_includes_contributing_states(self):
        incident = make_incident(contributing_states=6)
        prompt = build_incident_prompt(incident)
        assert "6" in prompt

    def test_includes_phases(self):
        incident = make_incident(phases=["cruise"])
        prompt = build_incident_prompt(incident)
        assert "cruise" in prompt

    def test_includes_evidence(self):
        incident = make_incident(
            evidence=["GPS quality degraded during flight"]
        )
        prompt = build_incident_prompt(incident)
        assert "GPS quality degraded during flight" in prompt

    def test_excludes_incident_id(self):
        """Prompt should not include incident_id (not needed for reasoning)."""
        incident = make_incident(incident_id="inc_secret_123")
        prompt = build_incident_prompt(incident)
        # The bounded contract does not include incident_id
        assert "inc_secret_123" not in prompt

    def test_excludes_mission_id(self):
        """Prompt should not include mission_id (not needed for reasoning)."""
        incident = make_incident(mission_id="mission_secret_456")
        prompt = build_incident_prompt(incident)
        assert "mission_secret_456" not in prompt

    def test_excludes_sequence_numbers(self):
        """Prompt should not include start/end sequence numbers."""
        incident = make_incident(start_sequence=5, end_sequence=10)
        prompt = build_incident_prompt(incident)
        # The bounded contract does not include sequence numbers
        assert "start_sequence" not in prompt
        assert "end_sequence" not in prompt

    def test_contains_valid_json_block(self):
        """Prompt should contain a parseable JSON block."""
        incident = make_incident()
        prompt = build_incident_prompt(incident)
        # Extract JSON from the prompt
        json_start = prompt.index("```json\n") + len("```json\n")
        json_end = prompt.index("\n```", json_start)
        json_str = prompt[json_start:json_end]
        parsed = json.loads(json_str)
        assert "incident_type" in parsed
        assert "severity" in parsed
        assert "evidence" in parsed

    def test_contains_task_instructions(self):
        incident = make_incident()
        prompt = build_incident_prompt(incident)
        assert "root cause" in prompt.lower()
        assert "confidence" in prompt.lower()
        assert "advisory" in prompt.lower()

    def test_battery_incident_prompt(self):
        incident = make_battery_incident()
        prompt = build_incident_prompt(incident)
        assert "battery_degradation" in prompt

    def test_minimal_incident_prompt(self):
        incident = make_minimal_incident()
        prompt = build_incident_prompt(incident)
        assert "telemetry_degradation" in prompt
        assert "low" in prompt
