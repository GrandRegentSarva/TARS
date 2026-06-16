"""
Phase 8 Reasoning Integration Tests
=====================================
Tests for Phase 8 integration with Phase 5 reasoning service.

Verifies:
- Existing Phase 5 behavior when introspection is disabled.
- use_introspection=false never calls Phoenix MCP.
- use_introspection=true adds bounded introspection context.
- Phoenix MCP failure does not fail reasoning.
- Reasoning result records introspection_used and consulted trace IDs.
- Prompt warns that trace history is not ground truth.
- No raw telemetry, credentials, or full trace bodies in outputs.

All tests run without live Phoenix, Gemini, Neo4j, PX4, or upstream APIs.
"""

from __future__ import annotations

from typing import Any, Optional

import pytest

from tars.phase8.config import MCPContentMode
from tars.phase8.models import (
    IntrospectionContext,
    IntrospectionResult,
    TraceSearchRequest,
)
from tars.phase8.phoenix_client import FakePhoenixTraceClient
from tars.phase8.service import IntrospectionService
from tars.phase8.summarizer import TraceSummarizer
from tars.phase8.tool_policy import IntrospectionPolicy

from .conftest import make_failed_trace, make_raw_trace, make_settings


class TestIntrospectionService:
    """Test the IntrospectionService orchestration."""

    @pytest.mark.asyncio
    async def test_search_traces_returns_results(self):
        """Search traces returns matching results."""
        settings = make_settings(enabled=True)
        client = FakePhoenixTraceClient()
        client.add_trace(make_raw_trace(trace_id="t1"))
        client.add_trace(make_raw_trace(trace_id="t2"))

        service = IntrospectionService(
            client=client,
            settings=settings,
        )

        request = TraceSearchRequest(limit=10)
        response = await service.search_traces(request)
        assert response.total == 2
        assert len(response.traces) == 2

    @pytest.mark.asyncio
    async def test_search_traces_empty_when_no_matches(self):
        """Search traces returns empty when no matches."""
        settings = make_settings(enabled=True)
        client = FakePhoenixTraceClient()

        service = IntrospectionService(
            client=client,
            settings=settings,
        )

        request = TraceSearchRequest(incident_type="nonexistent")
        response = await service.search_traces(request)
        assert response.total == 0
        assert response.traces == []

    @pytest.mark.asyncio
    async def test_search_traces_handles_client_failure(self):
        """Search traces returns empty on client failure."""
        settings = make_settings(enabled=True)
        client = FakePhoenixTraceClient(fail=True)

        service = IntrospectionService(
            client=client,
            settings=settings,
        )

        request = TraceSearchRequest()
        response = await service.search_traces(request)
        assert response.total == 0

    @pytest.mark.asyncio
    async def test_get_trace_summary(self):
        """Get trace summary returns summary for existing trace."""
        settings = make_settings(
            enabled=True,
            content_mode=MCPContentMode.SUMMARY,
        )
        client = FakePhoenixTraceClient()
        client.add_trace(make_raw_trace(trace_id="t1"))

        service = IntrospectionService(
            client=client,
            settings=settings,
        )

        from tars.phase8.models import TraceSummaryRequest
        response = await service.get_trace_summary(
            TraceSummaryRequest(trace_id="t1")
        )
        assert response is not None
        assert response.trace_id == "t1"
        assert len(response.stages) > 0

    @pytest.mark.asyncio
    async def test_get_trace_summary_not_found(self):
        """Get trace summary returns None for missing trace."""
        settings = make_settings(enabled=True)
        client = FakePhoenixTraceClient()

        service = IntrospectionService(
            client=client,
            settings=settings,
        )

        from tars.phase8.models import TraceSummaryRequest
        response = await service.get_trace_summary(
            TraceSummaryRequest(trace_id="nonexistent")
        )
        assert response is None

    @pytest.mark.asyncio
    async def test_compare_traces(self):
        """Compare traces returns descriptive comparison."""
        settings = make_settings(
            enabled=True,
            content_mode=MCPContentMode.SUMMARY,
        )
        client = FakePhoenixTraceClient()
        client.add_trace(make_raw_trace(trace_id="t1"))
        client.add_trace(make_raw_trace(trace_id="t2"))

        service = IntrospectionService(
            client=client,
            settings=settings,
        )

        from tars.phase8.models import TraceCompareRequest
        response = await service.compare_traces(
            TraceCompareRequest(trace_ids=["t1", "t2"])
        )
        assert response.not_an_evaluation is True
        assert len(response.trace_ids) == 2

    @pytest.mark.asyncio
    async def test_compare_traces_handles_failure(self):
        """Compare traces returns safe response on failure."""
        settings = make_settings(enabled=True)
        client = FakePhoenixTraceClient(fail=True)

        service = IntrospectionService(
            client=client,
            settings=settings,
        )

        from tars.phase8.models import TraceCompareRequest
        response = await service.compare_traces(
            TraceCompareRequest(trace_ids=["t1"])
        )
        assert response.not_an_evaluation is True


class TestBuildIntrospectionContext:
    """Test the high-level introspection context builder."""

    @pytest.mark.asyncio
    async def test_disabled_returns_empty(self):
        """Disabled introspection returns empty context."""
        settings = make_settings(enabled=False)
        service = IntrospectionService(settings=settings)

        context, result = await service.build_introspection_context(
            mission_id="m1",
            incident_id="i1",
            use_introspection=True,
        )
        assert context is None
        assert result.introspection_used is False

    @pytest.mark.asyncio
    async def test_not_requested_returns_empty(self):
        """Not-requested introspection returns empty context."""
        settings = make_settings(enabled=True)
        client = FakePhoenixTraceClient()
        client.add_trace(make_raw_trace())

        service = IntrospectionService(
            client=client,
            settings=settings,
        )

        context, result = await service.build_introspection_context(
            mission_id="m1",
            incident_id="i1",
            use_introspection=False,
        )
        assert context is None
        assert result.introspection_used is False
        # Verify Phoenix was never called
        assert len(client.search_calls) == 0

    @pytest.mark.asyncio
    async def test_enabled_with_traces(self):
        """Enabled introspection with matching traces returns context."""
        settings = make_settings(enabled=True)
        client = FakePhoenixTraceClient()
        client.add_trace(make_raw_trace(
            trace_id="t1",
            incident_type="navigation_instability",
        ))
        client.add_trace(make_raw_trace(
            trace_id="t2",
            incident_type="navigation_instability",
        ))

        service = IntrospectionService(
            client=client,
            settings=settings,
        )

        context, result = await service.build_introspection_context(
            mission_id="m1",
            incident_id="i1",
            incident_type="navigation_instability",
            use_introspection=True,
        )

        assert context is not None
        assert context.source == "phoenix_mcp"
        assert len(context.traces_consulted) == 2
        assert len(context.summary) > 0
        assert len(context.limitations) > 0

        assert result.introspection_used is True
        assert len(result.introspection_trace_ids) == 2
        assert result.introspection_summary is not None

    @pytest.mark.asyncio
    async def test_enabled_no_matching_traces(self):
        """Enabled introspection with no matching traces."""
        settings = make_settings(enabled=True)
        client = FakePhoenixTraceClient()

        service = IntrospectionService(
            client=client,
            settings=settings,
        )

        context, result = await service.build_introspection_context(
            mission_id="m1",
            incident_id="i1",
            incident_type="nonexistent",
            use_introspection=True,
        )

        assert context is None
        assert result.introspection_used is True
        assert "No prior traces" in (result.introspection_summary or "")

    @pytest.mark.asyncio
    async def test_phoenix_failure_does_not_fail_reasoning(self):
        """Phoenix MCP failure does not prevent reasoning."""
        settings = make_settings(enabled=True)
        client = FakePhoenixTraceClient(fail=True)

        service = IntrospectionService(
            client=client,
            settings=settings,
        )

        context, result = await service.build_introspection_context(
            mission_id="m1",
            incident_id="i1",
            use_introspection=True,
        )

        # Should not raise, should return graceful result
        # The service catches the failure and returns empty traces,
        # which results in "No prior traces found" message
        assert result.introspection_used is True
        assert result.introspection_summary is not None
        # Context should be None since no traces were found
        assert context is None

    @pytest.mark.asyncio
    async def test_unavailable_phoenix_returns_empty(self):
        """Unavailable Phoenix returns empty introspection."""
        settings = make_settings(enabled=True)
        client = FakePhoenixTraceClient(unavailable=True)

        service = IntrospectionService(
            client=client,
            settings=settings,
        )

        context, result = await service.build_introspection_context(
            mission_id="m1",
            incident_id="i1",
            use_introspection=True,
        )

        assert context is None
        assert result.introspection_used is True

    @pytest.mark.asyncio
    async def test_context_includes_limitations(self):
        """Introspection context includes explicit limitations."""
        settings = make_settings(enabled=True)
        client = FakePhoenixTraceClient()
        client.add_trace(make_raw_trace(trace_id="t1"))

        service = IntrospectionService(
            client=client,
            settings=settings,
        )

        context, result = await service.build_introspection_context(
            mission_id="m1",
            incident_id="i1",
            use_introspection=True,
        )

        assert context is not None
        assert any("descriptive" in lim.lower() for lim in context.limitations)
        assert any("evaluation" in lim.lower() or "accuracy" in lim.lower()
                    for lim in context.limitations)


class TestHealthCheck:
    """Test introspection service health check."""

    @pytest.mark.asyncio
    async def test_health_disabled(self):
        """Health returns 'disabled' when MCP is disabled."""
        settings = make_settings(enabled=False)
        service = IntrospectionService(settings=settings)
        status = await service.health_check()
        assert status == "disabled"

    @pytest.mark.asyncio
    async def test_health_ok(self):
        """Health returns 'ok' when Phoenix is reachable."""
        settings = make_settings(enabled=True)
        client = FakePhoenixTraceClient()
        service = IntrospectionService(
            client=client,
            settings=settings,
        )
        status = await service.health_check()
        assert status == "ok"

    @pytest.mark.asyncio
    async def test_health_unavailable(self):
        """Health returns 'unavailable' when Phoenix is unreachable."""
        settings = make_settings(enabled=True)
        client = FakePhoenixTraceClient(unavailable=True)
        service = IntrospectionService(
            client=client,
            settings=settings,
        )
        status = await service.health_check()
        assert status == "unavailable"


class TestPromptIntegration:
    """Test introspection context in reasoning prompts."""

    def test_prompt_without_introspection(self):
        """Prompt without introspection is unchanged."""
        from tars.phase5.prompts import build_incident_prompt

        incident = {
            "incident_type": "navigation_instability",
            "severity": "high",
            "start_ms": 5000,
            "end_ms": 10000,
            "contributing_states": 6,
            "peak_risk": 0.78,
            "phases": ["cruise"],
            "evidence": ["GPS quality degraded"],
        }

        prompt = build_incident_prompt(incident)
        assert "Prior reasoning trace context" not in prompt
        assert "navigation_instability" in prompt

    def test_prompt_with_introspection_context(self):
        """Prompt with introspection includes trace context."""
        from tars.phase5.prompts import build_incident_prompt

        incident = {
            "incident_type": "navigation_instability",
            "severity": "high",
            "start_ms": 5000,
            "end_ms": 10000,
            "contributing_states": 6,
            "peak_risk": 0.78,
            "phases": ["cruise"],
            "evidence": ["GPS quality degraded"],
        }

        context = IntrospectionContext(
            source="phoenix_mcp",
            traces_consulted=["t1", "t2"],
            summary=[
                "2 prior traces involved navigation_instability.",
                "Common root cause: gps_interference.",
            ],
            limitations=[
                "Trace history is descriptive and not an evaluation.",
                "No accuracy labels are available in Phase 8.",
            ],
        )

        prompt = build_incident_prompt(incident, introspection_context=context)

        # Verify introspection section is present
        assert "Prior reasoning trace context" in prompt
        assert "NOT ground truth" in prompt
        assert "t1" in prompt
        assert "t2" in prompt
        assert "navigation_instability" in prompt
        assert "gps_interference" in prompt

        # Verify limitations are present
        assert "descriptive" in prompt.lower()
        assert "not an evaluation" in prompt.lower()

    def test_prompt_warns_not_ground_truth(self):
        """Prompt explicitly warns that trace history is not ground truth."""
        from tars.phase5.prompts import build_incident_prompt

        incident = {
            "incident_type": "test",
            "severity": "low",
        }

        context = IntrospectionContext(
            traces_consulted=["t1"],
            summary=["One prior trace found."],
        )

        prompt = build_incident_prompt(incident, introspection_context=context)
        assert "NOT ground truth" in prompt
        assert "NOT been validated" in prompt


class TestPhase5ModelIntegration:
    """Test Phase 5 model changes for Phase 8 integration."""

    def test_analyze_request_default_no_introspection(self):
        """AnalyzeRequest defaults to use_introspection=False."""
        from tars.phase5.models import AnalyzeRequest

        req = AnalyzeRequest()
        assert req.use_introspection is False

    def test_analyze_request_with_introspection(self):
        """AnalyzeRequest accepts use_introspection=True."""
        from tars.phase5.models import AnalyzeRequest

        req = AnalyzeRequest(use_introspection=True)
        assert req.use_introspection is True

    def test_reasoning_result_default_no_introspection(self):
        """ReasoningResult defaults to no introspection metadata."""
        from tars.phase5.models import ReasoningResult

        result = ReasoningResult(
            reasoning_id="r1",
            mission_id="m1",
            incident_id="i1",
            incident_type="test",
            root_cause="test_cause",
            confidence=0.5,
            recommendation="consider investigating further",
            rationale="test rationale",
            model="test-model",
            prompt_version="1.0.0",
            created_at="2026-06-15T10:30:00Z",
        )
        assert result.introspection_used is False
        assert result.introspection_trace_ids == []
        assert result.introspection_summary is None

    def test_reasoning_result_with_introspection(self):
        """ReasoningResult accepts introspection metadata."""
        from tars.phase5.models import ReasoningResult

        result = ReasoningResult(
            reasoning_id="r1",
            mission_id="m1",
            incident_id="i1",
            incident_type="test",
            root_cause="test_cause",
            confidence=0.5,
            recommendation="consider investigating further",
            rationale="test rationale",
            model="test-model",
            prompt_version="1.0.0",
            created_at="2026-06-15T10:30:00Z",
            introspection_used=True,
            introspection_trace_ids=["t1", "t2"],
            introspection_summary="Prior traces showed gps_interference.",
        )
        assert result.introspection_used is True
        assert result.introspection_trace_ids == ["t1", "t2"]
        assert "gps_interference" in result.introspection_summary

    def test_analyze_response_includes_introspection(self):
        """AnalyzeResponse includes introspection fields."""
        from tars.phase5.models import AnalyzeResponse

        resp = AnalyzeResponse(
            reasoning_id="r1",
            mission_id="m1",
            incident_id="i1",
            incident_type="test",
            root_cause="test_cause",
            confidence=0.5,
            recommendation="consider investigating",
            rationale="test",
            model="test",
            prompt_version="1.0.0",
            created_at="2026-06-15T10:30:00Z",
            introspection_used=True,
            introspection_trace_ids=["t1"],
            introspection_summary="test summary",
        )
        assert resp.introspection_used is True

    def test_health_response_includes_phoenix_mcp(self):
        """HealthResponse includes phoenix_mcp field."""
        from tars.phase5.models import HealthResponse

        resp = HealthResponse()
        assert resp.phoenix_mcp == "disabled"

        resp = HealthResponse(phoenix_mcp="ok")
        assert resp.phoenix_mcp == "ok"


class TestNoEvaluationScores:
    """Verify Phase 8 does not create evaluation scores or knowledge."""

    def test_comparison_is_not_evaluation(self):
        """Comparison output is descriptive, not evaluative."""
        from tars.phase8.models import TraceCompareResponse

        resp = TraceCompareResponse(
            trace_ids=["t1", "t2"],
            observed_pattern="Both traces failed at gemini.generate.",
        )
        assert resp.not_an_evaluation is True

    def test_cannot_create_evaluation_comparison(self):
        """Cannot create a comparison marked as evaluation."""
        from tars.phase8.models import TraceCompareResponse

        with pytest.raises(ValueError):
            TraceCompareResponse(
                trace_ids=["t1"],
                not_an_evaluation=False,
            )

    def test_introspection_context_has_limitations(self):
        """Introspection context always includes limitations."""
        ctx = IntrospectionContext()
        assert len(ctx.limitations) >= 1
        assert any("not an evaluation" in lim.lower() for lim in ctx.limitations)

    def test_no_accuracy_labels(self):
        """No accuracy labels in introspection results."""
        result = IntrospectionResult(
            introspection_used=True,
            introspection_trace_ids=["t1"],
            introspection_summary="Prior traces consulted.",
        )
        # Verify no accuracy/score fields exist
        fields = result.model_fields
        for field_name in fields:
            assert "accuracy" not in field_name.lower()
            assert "score" not in field_name.lower()
            assert "evaluation" not in field_name.lower()


class TestNoRawContent:
    """Verify no raw telemetry, credentials, or full trace bodies."""

    def test_trace_metadata_no_raw_content(self):
        """TraceMetadata has no raw content fields."""
        from tars.phase8.models import TraceMetadata

        fields = TraceMetadata.model_fields
        for field_name in fields:
            assert "raw" not in field_name.lower()
            assert "telemetry" not in field_name.lower()
            assert "replay" not in field_name.lower()
            assert "credential" not in field_name.lower()
            assert "password" not in field_name.lower()

    def test_trace_summary_no_raw_content(self):
        """TraceSummary has no raw content fields."""
        from tars.phase8.models import TraceSummary

        fields = TraceSummary.model_fields
        for field_name in fields:
            assert "raw" not in field_name.lower()
            assert "telemetry" not in field_name.lower()
            assert "credential" not in field_name.lower()

    def test_introspection_context_no_raw_content(self):
        """IntrospectionContext has no raw content fields."""
        fields = IntrospectionContext.model_fields
        for field_name in fields:
            assert "raw" not in field_name.lower()
            assert "telemetry" not in field_name.lower()
            assert "credential" not in field_name.lower()
