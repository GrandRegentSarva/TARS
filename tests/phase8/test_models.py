"""
Phase 8 Model Tests
====================
Tests for tool request models, safe trace summaries, and introspection
metadata.

All tests run without live Phoenix, Gemini, or MCP network services.
"""

from __future__ import annotations

import pytest

from tars.phase8.models import (
    IntrospectionContext,
    IntrospectionResult,
    TraceCompareRequest,
    TraceCompareResponse,
    TraceMetadata,
    TraceSearchRequest,
    TraceSearchResponse,
    TraceStage,
    TraceSummary,
    TraceSummaryRequest,
    TraceSummaryResponse,
    _redact_secrets,
    _truncate,
)


class TestTraceSearchRequest:
    """Test TraceSearchRequest model validation."""

    def test_default_limit(self):
        """Default limit is 5."""
        req = TraceSearchRequest()
        assert req.limit == 5

    def test_positive_limit_required(self):
        """Limit must be at least 1."""
        with pytest.raises(ValueError):
            TraceSearchRequest(limit=0)

    def test_limit_capped_to_max(self):
        """Limit is capped to configured maximum (20)."""
        req = TraceSearchRequest(limit=100)
        assert req.limit == 20

    def test_valid_outcome_values(self):
        """Valid outcome values are accepted."""
        for outcome in ("success", "failed", "cached"):
            req = TraceSearchRequest(outcome=outcome)
            assert req.outcome == outcome

    def test_invalid_outcome_rejected(self):
        """Invalid outcome values are rejected."""
        with pytest.raises(ValueError, match="outcome must be"):
            TraceSearchRequest(outcome="invalid")

    def test_all_filters_optional(self):
        """All filter fields are optional."""
        req = TraceSearchRequest()
        assert req.mission_id is None
        assert req.incident_id is None
        assert req.incident_type is None
        assert req.root_cause is None
        assert req.prompt_version is None
        assert req.model is None
        assert req.outcome is None
        assert req.from_time is None
        assert req.to_time is None

    def test_filters_set_correctly(self):
        """Filter values are preserved."""
        req = TraceSearchRequest(
            mission_id="m1",
            incident_type="nav",
            root_cause="gps",
            limit=3,
        )
        assert req.mission_id == "m1"
        assert req.incident_type == "nav"
        assert req.root_cause == "gps"
        assert req.limit == 3


class TestTraceSummaryRequest:
    """Test TraceSummaryRequest model validation."""

    def test_trace_id_required(self):
        """trace_id is required."""
        with pytest.raises(ValueError):
            TraceSummaryRequest(trace_id="")

    def test_valid_trace_id(self):
        """Valid trace_id is accepted."""
        req = TraceSummaryRequest(trace_id="abc123")
        assert req.trace_id == "abc123"


class TestTraceCompareRequest:
    """Test TraceCompareRequest model validation."""

    def test_trace_ids_required(self):
        """At least one trace ID is required."""
        with pytest.raises(ValueError):
            TraceCompareRequest(trace_ids=[])

    def test_empty_ids_rejected(self):
        """Empty string trace IDs are rejected."""
        with pytest.raises(ValueError, match="non-empty"):
            TraceCompareRequest(trace_ids=["", "  "])

    def test_trace_ids_capped(self):
        """Trace IDs are capped to configured maximum (10)."""
        ids = [f"trace_{i}" for i in range(15)]
        req = TraceCompareRequest(trace_ids=ids)
        assert len(req.trace_ids) == 10

    def test_valid_trace_ids(self):
        """Valid trace IDs are accepted."""
        req = TraceCompareRequest(trace_ids=["a", "b", "c"])
        assert req.trace_ids == ["a", "b", "c"]


class TestTraceStage:
    """Test TraceStage model."""

    def test_basic_stage(self):
        """Basic stage creation works."""
        stage = TraceStage(name="gemini.generate", status="ok", duration_ms=100)
        assert stage.name == "gemini.generate"
        assert stage.status == "ok"
        assert stage.duration_ms == 100

    def test_error_stage_with_safe_error(self):
        """Error stage with safe error message."""
        stage = TraceStage(
            name="gemini.generate",
            status="error",
            safe_error="provider timeout",
        )
        assert stage.safe_error == "provider timeout"

    def test_secret_redaction_in_error(self):
        """Secret-like content is redacted from error messages."""
        stage = TraceStage(
            name="test",
            status="error",
            safe_error="Failed with api_key=sk-12345",
        )
        assert "sk-12345" not in stage.safe_error
        assert "[REDACTED]" in stage.safe_error

    def test_error_truncation(self):
        """Long error messages are truncated."""
        long_error = "x" * 1000
        stage = TraceStage(name="test", status="error", safe_error=long_error)
        assert len(stage.safe_error) <= 500


class TestTraceMetadata:
    """Test TraceMetadata model."""

    def test_minimal_metadata(self):
        """Minimal metadata with just trace_id."""
        meta = TraceMetadata(trace_id="abc123")
        assert meta.trace_id == "abc123"
        assert meta.reasoning_id is None
        assert meta.mission_id is None

    def test_full_metadata(self):
        """Full metadata with all fields."""
        meta = TraceMetadata(
            trace_id="abc123",
            reasoning_id="reason_001",
            mission_id="mission_001",
            incident_id="inc_001",
            incident_type="navigation_instability",
            root_cause="gps_interference",
            confidence=0.72,
            prompt_version="1.0.0",
            model="gemini-2.5-flash",
            outcome="success",
            duration_ms=1280,
            created_at="2026-06-15T10:30:00Z",
        )
        assert meta.confidence == 0.72
        assert meta.outcome == "success"

    def test_confidence_bounds(self):
        """Confidence must be between 0.0 and 1.0."""
        with pytest.raises(ValueError):
            TraceMetadata(trace_id="x", confidence=1.5)
        with pytest.raises(ValueError):
            TraceMetadata(trace_id="x", confidence=-0.1)


class TestTraceSummary:
    """Test TraceSummary model."""

    def test_summary_truncation(self):
        """Overlong summaries are truncated."""
        long_summary = "x" * 3000
        summary = TraceSummary(trace_id="abc", summary=long_summary)
        assert len(summary.summary) <= 2000
        assert summary.summary.endswith("...[truncated]")

    def test_default_captured_content(self):
        """Default captured_content is 'metadata'."""
        summary = TraceSummary(trace_id="abc")
        assert summary.captured_content == "metadata"


class TestTraceCompareResponse:
    """Test TraceCompareResponse model."""

    def test_not_an_evaluation_always_true(self):
        """not_an_evaluation must always be True."""
        resp = TraceCompareResponse(trace_ids=["a"])
        assert resp.not_an_evaluation is True

    def test_not_an_evaluation_cannot_be_false(self):
        """Setting not_an_evaluation to False raises ValueError."""
        with pytest.raises(ValueError, match="not_an_evaluation must always be True"):
            TraceCompareResponse(trace_ids=["a"], not_an_evaluation=False)

    def test_observed_pattern_truncation(self):
        """Overlong observed_pattern is truncated."""
        long_pattern = "x" * 3000
        resp = TraceCompareResponse(
            trace_ids=["a"],
            observed_pattern=long_pattern,
        )
        assert len(resp.observed_pattern) <= 2000


class TestIntrospectionContext:
    """Test IntrospectionContext model."""

    def test_default_limitations(self):
        """Default limitations are set."""
        ctx = IntrospectionContext()
        assert len(ctx.limitations) == 2
        assert "descriptive" in ctx.limitations[0].lower()

    def test_summary_truncation(self):
        """Individual summary items are truncated."""
        long_items = ["x" * 1000 for _ in range(5)]
        ctx = IntrospectionContext(summary=long_items)
        for item in ctx.summary:
            assert len(item) <= 500

    def test_summary_count_capped(self):
        """Summary items are capped at 20."""
        items = [f"item_{i}" for i in range(30)]
        ctx = IntrospectionContext(summary=items)
        assert len(ctx.summary) <= 20


class TestIntrospectionResult:
    """Test IntrospectionResult model."""

    def test_default_not_used(self):
        """Default introspection_used is False."""
        result = IntrospectionResult()
        assert result.introspection_used is False
        assert result.introspection_trace_ids == []
        assert result.introspection_summary is None

    def test_summary_truncation(self):
        """Overlong introspection_summary is truncated."""
        long_summary = "x" * 3000
        result = IntrospectionResult(
            introspection_used=True,
            introspection_summary=long_summary,
        )
        assert len(result.introspection_summary) <= 2000


class TestHelpers:
    """Test helper functions."""

    def test_redact_secrets_api_key(self):
        """API key patterns are redacted."""
        text = "Error: api_key=sk-12345 is invalid"
        result = _redact_secrets(text)
        assert "sk-12345" not in result
        assert "[REDACTED]" in result

    def test_redact_secrets_redis_url(self):
        """Redis URLs are redacted."""
        text = "Connected to redis://user:pass@host:6379"
        result = _redact_secrets(text)
        assert "[REDACTED]" in result

    def test_redact_secrets_bearer_token(self):
        """Bearer tokens are redacted."""
        text = "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9"
        result = _redact_secrets(text)
        assert "[REDACTED]" in result

    def test_redact_secrets_safe_text(self):
        """Safe text is not modified."""
        text = "GPS quality degraded during flight"
        result = _redact_secrets(text)
        assert result == text

    def test_truncate_short_text(self):
        """Short text is not truncated."""
        text = "short"
        result = _truncate(text, 100)
        assert result == text

    def test_truncate_long_text(self):
        """Long text is truncated with marker."""
        text = "x" * 200
        result = _truncate(text, 100)
        assert len(result) <= 100
        assert result.endswith("...[truncated]")
