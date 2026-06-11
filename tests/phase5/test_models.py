"""
Tests for Phase 5 Reasoning Models
====================================
Tests Pydantic model validation, confidence bounds, advisory constraints,
and structured output validation.
"""

from __future__ import annotations

import pytest

from tars.phase5.models import ReasoningAnalysis, ReasoningResult


# =============================================================================
# ReasoningAnalysis Validation
# =============================================================================

class TestReasoningAnalysis:
    """Test ReasoningAnalysis model validation."""

    def test_valid_analysis(self):
        analysis = ReasoningAnalysis(
            root_cause="gps_interference",
            confidence=0.85,
            recommendation="consider switching to visual navigation",
            rationale="GPS degradation preceded attitude instability.",
            contributing_factors=["weak GPS quality during cruise"],
            uncertainties=["No environmental data available"],
        )
        assert analysis.root_cause == "gps_interference"
        assert analysis.confidence == 0.85

    def test_confidence_lower_bound(self):
        analysis = ReasoningAnalysis(
            root_cause="test",
            confidence=0.0,
            recommendation="consider investigating",
            rationale="Low confidence analysis.",
            contributing_factors=[],
            uncertainties=[],
        )
        assert analysis.confidence == 0.0

    def test_confidence_upper_bound(self):
        analysis = ReasoningAnalysis(
            root_cause="test",
            confidence=1.0,
            recommendation="consider investigating",
            rationale="High confidence analysis.",
            contributing_factors=[],
            uncertainties=[],
        )
        assert analysis.confidence == 1.0

    def test_confidence_below_zero_rejected(self):
        with pytest.raises(ValueError):
            ReasoningAnalysis(
                root_cause="test",
                confidence=-0.1,
                recommendation="consider investigating",
                rationale="Invalid.",
                contributing_factors=[],
                uncertainties=[],
            )

    def test_confidence_above_one_rejected(self):
        with pytest.raises(ValueError):
            ReasoningAnalysis(
                root_cause="test",
                confidence=1.1,
                recommendation="consider investigating",
                rationale="Invalid.",
                contributing_factors=[],
                uncertainties=[],
            )

    def test_empty_root_cause_rejected(self):
        with pytest.raises(ValueError):
            ReasoningAnalysis(
                root_cause="",
                confidence=0.5,
                recommendation="consider investigating",
                rationale="Some rationale.",
                contributing_factors=[],
                uncertainties=[],
            )

    def test_empty_recommendation_rejected(self):
        with pytest.raises(ValueError):
            ReasoningAnalysis(
                root_cause="test",
                confidence=0.5,
                recommendation="",
                rationale="Some rationale.",
                contributing_factors=[],
                uncertainties=[],
            )

    def test_empty_rationale_rejected(self):
        with pytest.raises(ValueError):
            ReasoningAnalysis(
                root_cause="test",
                confidence=0.5,
                recommendation="consider investigating",
                rationale="",
                contributing_factors=[],
                uncertainties=[],
            )

    def test_control_command_execute_rejected(self):
        with pytest.raises(ValueError, match="control pattern"):
            ReasoningAnalysis(
                root_cause="test",
                confidence=0.5,
                recommendation="execute emergency landing procedure",
                rationale="Some rationale.",
                contributing_factors=[],
                uncertainties=[],
            )

    def test_control_command_arm_rejected(self):
        with pytest.raises(ValueError, match="control pattern"):
            ReasoningAnalysis(
                root_cause="test",
                confidence=0.5,
                recommendation="arm the motors and takeoff",
                rationale="Some rationale.",
                contributing_factors=[],
                uncertainties=[],
            )

    def test_control_command_disarm_rejected(self):
        with pytest.raises(ValueError, match="control pattern"):
            ReasoningAnalysis(
                root_cause="test",
                confidence=0.5,
                recommendation="disarm the drone immediately",
                rationale="Some rationale.",
                contributing_factors=[],
                uncertainties=[],
            )

    def test_control_command_land_rejected(self):
        with pytest.raises(ValueError, match="control pattern"):
            ReasoningAnalysis(
                root_cause="test",
                confidence=0.5,
                recommendation="land the drone now",
                rationale="Some rationale.",
                contributing_factors=[],
                uncertainties=[],
            )

    def test_control_command_set_mode_rejected(self):
        with pytest.raises(ValueError, match="control pattern"):
            ReasoningAnalysis(
                root_cause="test",
                confidence=0.5,
                recommendation="set_mode to HOLD",
                rationale="Some rationale.",
                contributing_factors=[],
                uncertainties=[],
            )

    def test_control_command_mavsdk_rejected(self):
        with pytest.raises(ValueError, match="control pattern"):
            ReasoningAnalysis(
                root_cause="test",
                confidence=0.5,
                recommendation="use mavsdk to send RTL command",
                rationale="Some rationale.",
                contributing_factors=[],
                uncertainties=[],
            )

    def test_control_command_mavlink_rejected(self):
        with pytest.raises(ValueError, match="control pattern"):
            ReasoningAnalysis(
                root_cause="test",
                confidence=0.5,
                recommendation="send mavlink message to autopilot",
                rationale="Some rationale.",
                contributing_factors=[],
                uncertainties=[],
            )

    def test_control_command_rtl_rejected(self):
        with pytest.raises(ValueError, match="control pattern"):
            ReasoningAnalysis(
                root_cause="test",
                confidence=0.5,
                recommendation="return_to_launch immediately",
                rationale="Some rationale.",
                contributing_factors=[],
                uncertainties=[],
            )

    def test_control_command_kill_rejected(self):
        with pytest.raises(ValueError, match="control pattern"):
            ReasoningAnalysis(
                root_cause="test",
                confidence=0.5,
                recommendation="kill the motors",
                rationale="Some rationale.",
                contributing_factors=[],
                uncertainties=[],
            )

    def test_control_command_descend_immediately_rejected(self):
        """'descend immediately' should be rejected as a control command."""
        with pytest.raises(ValueError, match="control pattern"):
            ReasoningAnalysis(
                root_cause="test",
                confidence=0.5,
                recommendation="descend immediately to safe altitude",
                rationale="Some rationale.",
                contributing_factors=[],
                uncertainties=[],
            )

    def test_control_command_fly_to_rejected(self):
        """'fly to' should be rejected as a control command."""
        with pytest.raises(ValueError, match="control pattern"):
            ReasoningAnalysis(
                root_cause="test",
                confidence=0.5,
                recommendation="fly to the nearest landing zone",
                rationale="Some rationale.",
                contributing_factors=[],
                uncertainties=[],
            )

    def test_word_boundary_landing_accepted(self):
        """'landing' should NOT trigger the 'land' pattern (word boundary)."""
        analysis = ReasoningAnalysis(
            root_cause="test",
            confidence=0.5,
            recommendation="consider inspecting the landing gear before next flight",
            rationale="Some rationale.",
            contributing_factors=[],
            uncertainties=[],
        )
        assert "landing" in analysis.recommendation

    def test_word_boundary_disarming_accepted(self):
        """'disarming' should NOT trigger the 'disarm' pattern (word boundary)."""
        analysis = ReasoningAnalysis(
            root_cause="test",
            confidence=0.5,
            recommendation="consider reviewing the disarming procedure documentation",
            rationale="Some rationale.",
            contributing_factors=[],
            uncertainties=[],
        )
        assert "disarming" in analysis.recommendation

    def test_word_boundary_armed_accepted(self):
        """'armed' should NOT trigger the 'arm' pattern (word boundary)."""
        analysis = ReasoningAnalysis(
            root_cause="test",
            confidence=0.5,
            recommendation="consider checking if the drone was armed correctly",
            rationale="Some rationale.",
            contributing_factors=[],
            uncertainties=[],
        )
        assert "armed" in analysis.recommendation

    def test_word_boundary_execution_accepted(self):
        """'execution' should NOT trigger the 'execute' pattern (word boundary)."""
        analysis = ReasoningAnalysis(
            root_cause="test",
            confidence=0.5,
            recommendation="consider reviewing mission execution logs",
            rationale="Some rationale.",
            contributing_factors=[],
            uncertainties=[],
        )
        assert "execution" in analysis.recommendation

    def test_word_boundary_killer_accepted(self):
        """'killer' should NOT trigger the 'kill' pattern (word boundary)."""
        analysis = ReasoningAnalysis(
            root_cause="test",
            confidence=0.5,
            recommendation="consider investigating the battery killer drain issue",
            rationale="Some rationale.",
            contributing_factors=[],
            uncertainties=[],
        )
        assert "killer" in analysis.recommendation

    def test_advisory_recommendation_accepted(self):
        """Advisory language should be accepted."""
        analysis = ReasoningAnalysis(
            root_cause="gps_interference",
            confidence=0.8,
            recommendation=(
                "consider switching to visual navigation and "
                "evaluate GPS interference sources"
            ),
            rationale="GPS degradation observed.",
            contributing_factors=["weak GPS"],
            uncertainties=[],
        )
        assert "consider" in analysis.recommendation

    def test_defaults_for_lists(self):
        analysis = ReasoningAnalysis(
            root_cause="test",
            confidence=0.5,
            recommendation="consider investigating",
            rationale="Some rationale.",
        )
        assert analysis.contributing_factors == []
        assert analysis.uncertainties == []


# =============================================================================
# ReasoningResult Validation
# =============================================================================

class TestReasoningResult:
    """Test ReasoningResult model validation."""

    def test_valid_result(self):
        result = ReasoningResult(
            reasoning_id="reason_abc123",
            mission_id="test_mission",
            incident_id="inc_test123",
            incident_type="navigation_instability",
            root_cause="gps_interference",
            confidence=0.85,
            recommendation="consider switching to visual navigation",
            rationale="GPS degradation preceded attitude instability.",
            contributing_factors=["weak GPS quality"],
            uncertainties=["No environmental data"],
            model="gemini-2.5-flash",
            prompt_version="1.0.0",
            created_at="2026-06-11T12:00:00+00:00",
            advisory_only=True,
        )
        assert result.advisory_only is True
        assert result.reasoning_id == "reason_abc123"

    def test_advisory_only_must_be_true(self):
        with pytest.raises(ValueError, match="advisory_only must always be True"):
            ReasoningResult(
                reasoning_id="reason_abc123",
                mission_id="test_mission",
                incident_id="inc_test123",
                incident_type="navigation_instability",
                root_cause="gps_interference",
                confidence=0.85,
                recommendation="consider investigating",
                rationale="Some rationale.",
                contributing_factors=[],
                uncertainties=[],
                model="gemini-2.5-flash",
                prompt_version="1.0.0",
                created_at="2026-06-11T12:00:00+00:00",
                advisory_only=False,
            )

    def test_confidence_bounds_in_result(self):
        with pytest.raises(ValueError):
            ReasoningResult(
                reasoning_id="reason_abc123",
                mission_id="test_mission",
                incident_id="inc_test123",
                incident_type="navigation_instability",
                root_cause="gps_interference",
                confidence=1.5,
                recommendation="consider investigating",
                rationale="Some rationale.",
                contributing_factors=[],
                uncertainties=[],
                model="gemini-2.5-flash",
                prompt_version="1.0.0",
                created_at="2026-06-11T12:00:00+00:00",
                advisory_only=True,
            )

    def test_control_command_rejected_in_result(self):
        """ReasoningResult must also reject control commands in recommendation."""
        with pytest.raises(ValueError, match="control pattern"):
            ReasoningResult(
                reasoning_id="reason_abc123",
                mission_id="test_mission",
                incident_id="inc_test123",
                incident_type="navigation_instability",
                root_cause="gps_interference",
                confidence=0.85,
                recommendation="execute emergency landing now",
                rationale="Some rationale.",
                contributing_factors=[],
                uncertainties=[],
                model="gemini-2.5-flash",
                prompt_version="1.0.0",
                created_at="2026-06-11T12:00:00+00:00",
                advisory_only=True,
            )

    def test_control_command_rejected_on_deserialization(self):
        """ReasoningResult must reject control commands even during deserialization."""
        import json as json_mod
        raw = json_mod.dumps({
            "reasoning_id": "reason_abc123",
            "mission_id": "test_mission",
            "incident_id": "inc_test123",
            "incident_type": "navigation_instability",
            "root_cause": "gps_interference",
            "confidence": 0.85,
            "recommendation": "land the drone immediately",
            "rationale": "Some rationale.",
            "contributing_factors": [],
            "uncertainties": [],
            "model": "gemini-2.5-flash",
            "prompt_version": "1.0.0",
            "created_at": "2026-06-11T12:00:00+00:00",
            "advisory_only": True,
        })
        with pytest.raises(ValueError, match="control pattern"):
            ReasoningResult.model_validate_json(raw)

    def test_serialization_roundtrip(self):
        result = ReasoningResult(
            reasoning_id="reason_abc123",
            mission_id="test_mission",
            incident_id="inc_test123",
            incident_type="navigation_instability",
            root_cause="gps_interference",
            confidence=0.85,
            recommendation="consider investigating",
            rationale="Some rationale.",
            contributing_factors=["factor1", "factor2"],
            uncertainties=["uncertainty1"],
            model="gemini-2.5-flash",
            prompt_version="1.0.0",
            created_at="2026-06-11T12:00:00+00:00",
            advisory_only=True,
        )
        json_str = result.model_dump_json()
        restored = ReasoningResult.model_validate_json(json_str)
        assert restored.reasoning_id == result.reasoning_id
        assert restored.confidence == result.confidence
        assert restored.contributing_factors == result.contributing_factors
