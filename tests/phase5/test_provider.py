"""
Tests for Phase 5 Reasoning Providers
=======================================
Tests the fake provider and validates provider output before persistence.
No live Gemini calls in the automated test suite.
"""

from __future__ import annotations

import pytest

from tars.phase5.models import ReasoningAnalysis
from tars.phase5.provider import FakeReasoningProvider

from .conftest import (
    make_incident,
    make_battery_incident,
    make_critical_incident,
    make_minimal_incident,
)


# =============================================================================
# Fake Provider Tests
# =============================================================================

class TestFakeProvider:
    """Test the deterministic fake reasoning provider."""

    @pytest.mark.asyncio
    async def test_analyze_returns_analysis(self):
        provider = FakeReasoningProvider()
        incident = make_incident()
        result = await provider.analyze(incident)
        assert isinstance(result, ReasoningAnalysis)
        assert result.root_cause == "gps_interference"
        assert 0.0 <= result.confidence <= 1.0

    @pytest.mark.asyncio
    async def test_model_name(self):
        provider = FakeReasoningProvider(model_name="test-model-v1")
        assert provider.model_name == "test-model-v1"

    @pytest.mark.asyncio
    async def test_is_configured(self):
        provider = FakeReasoningProvider(configured=True)
        assert provider.is_configured() is True

    @pytest.mark.asyncio
    async def test_is_not_configured(self):
        provider = FakeReasoningProvider(configured=False)
        assert provider.is_configured() is False

    @pytest.mark.asyncio
    async def test_unconfigured_raises(self):
        provider = FakeReasoningProvider(configured=False)
        with pytest.raises(RuntimeError, match="not configured"):
            await provider.analyze(make_incident())

    @pytest.mark.asyncio
    async def test_failing_provider_raises(self):
        provider = FakeReasoningProvider(fail=True, fail_message="Boom")
        with pytest.raises(ValueError, match="Boom"):
            await provider.analyze(make_incident())

    @pytest.mark.asyncio
    async def test_call_count_tracks(self):
        provider = FakeReasoningProvider()
        assert provider.call_count == 0
        await provider.analyze(make_incident())
        assert provider.call_count == 1
        await provider.analyze(make_incident())
        assert provider.call_count == 2

    @pytest.mark.asyncio
    async def test_last_incident_tracked(self):
        provider = FakeReasoningProvider()
        incident = make_incident(incident_id="inc_tracked")
        await provider.analyze(incident)
        assert provider.last_incident is not None
        assert provider.last_incident["incident_id"] == "inc_tracked"

    @pytest.mark.asyncio
    async def test_custom_response(self):
        custom = ReasoningAnalysis(
            root_cause="custom_cause",
            confidence=0.42,
            recommendation="consider custom action",
            rationale="Custom rationale.",
            contributing_factors=["custom factor"],
            uncertainties=["custom uncertainty"],
        )
        provider = FakeReasoningProvider(custom_response=custom)
        result = await provider.analyze(make_incident())
        assert result.root_cause == "custom_cause"
        assert result.confidence == 0.42


# =============================================================================
# Provider Output Validation Tests
# =============================================================================

class TestProviderOutputValidation:
    """Test that provider output is validated before persistence."""

    @pytest.mark.asyncio
    async def test_navigation_incident_analysis(self):
        provider = FakeReasoningProvider()
        incident = make_incident(incident_type="navigation_instability")
        result = await provider.analyze(incident)
        assert result.root_cause == "gps_interference"
        assert result.confidence > 0.0
        assert len(result.recommendation) > 0
        assert len(result.rationale) > 0

    @pytest.mark.asyncio
    async def test_battery_incident_analysis(self):
        provider = FakeReasoningProvider()
        incident = make_battery_incident()
        result = await provider.analyze(incident)
        assert result.root_cause == "accelerated_discharge"
        assert "battery" in result.recommendation.lower()

    @pytest.mark.asyncio
    async def test_critical_incident_higher_confidence(self):
        provider = FakeReasoningProvider()
        critical = make_critical_incident()
        minimal = make_minimal_incident()
        critical_result = await provider.analyze(critical)
        minimal_result = await provider.analyze(minimal)
        # Critical incident with more evidence should have higher confidence
        assert critical_result.confidence > minimal_result.confidence

    @pytest.mark.asyncio
    async def test_minimal_evidence_has_uncertainties(self):
        provider = FakeReasoningProvider()
        incident = make_minimal_incident()
        result = await provider.analyze(incident)
        assert len(result.uncertainties) > 0

    @pytest.mark.asyncio
    async def test_high_risk_adds_contributing_factor(self):
        provider = FakeReasoningProvider()
        incident = make_incident(peak_risk=0.85)
        result = await provider.analyze(incident)
        risk_factors = [
            f for f in result.contributing_factors
            if "risk" in f.lower()
        ]
        assert len(risk_factors) > 0

    @pytest.mark.asyncio
    async def test_all_incident_types_produce_valid_output(self):
        """Every incident type should produce a valid ReasoningAnalysis."""
        provider = FakeReasoningProvider()
        incident_types = [
            "navigation_instability",
            "battery_degradation",
            "attitude_instability",
            "altitude_instability",
            "sensor_health_failure",
            "telemetry_degradation",
            "high_risk_state",
        ]
        for itype in incident_types:
            incident = make_incident(incident_type=itype)
            result = await provider.analyze(incident)
            assert isinstance(result, ReasoningAnalysis)
            assert 0.0 <= result.confidence <= 1.0
            assert len(result.root_cause) > 0
            assert len(result.recommendation) > 0
            assert len(result.rationale) > 0

    @pytest.mark.asyncio
    async def test_unknown_incident_type_handled(self):
        provider = FakeReasoningProvider()
        incident = make_incident(incident_type="unknown_type")
        result = await provider.analyze(incident)
        assert result.root_cause == "undetermined"
