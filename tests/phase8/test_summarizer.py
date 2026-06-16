"""
Phase 8 Summarizer Tests
=========================
Tests for raw trace-to-safe-summary conversion.

All tests run without live Phoenix, Gemini, or MCP network services.
"""

from __future__ import annotations

import pytest

from tars.phase8.config import MCPContentMode
from tars.phase8.summarizer import TraceSummarizer

from .conftest import make_failed_trace, make_raw_trace, make_settings


class TestSummarizeTraceMetadata:
    """Test trace metadata extraction."""

    def test_extracts_trace_id(self):
        """Extracts trace_id from raw trace."""
        settings = make_settings()
        summarizer = TraceSummarizer(settings=settings)
        raw = make_raw_trace(trace_id="trace_xyz")
        meta = summarizer.summarize_trace_metadata(raw)
        assert meta.trace_id == "trace_xyz"

    def test_extracts_tars_attributes(self):
        """Extracts TARS-specific attributes."""
        settings = make_settings()
        summarizer = TraceSummarizer(settings=settings)
        raw = make_raw_trace(
            mission_id="m1",
            incident_id="i1",
            incident_type="nav",
            reasoning_id="r1",
            root_cause="gps",
            confidence=0.8,
            prompt_version="1.0.0",
            model="gemini-2.5-flash",
            outcome="success",
        )
        meta = summarizer.summarize_trace_metadata(raw)
        assert meta.mission_id == "m1"
        assert meta.incident_id == "i1"
        assert meta.incident_type == "nav"
        assert meta.reasoning_id == "r1"
        assert meta.root_cause == "gps"
        assert meta.confidence == 0.8
        assert meta.prompt_version == "1.0.0"
        assert meta.model == "gemini-2.5-flash"
        assert meta.outcome == "success"

    def test_handles_missing_attributes(self):
        """Handles traces with missing attributes gracefully."""
        settings = make_settings()
        summarizer = TraceSummarizer(settings=settings)
        raw = {"trace_id": "minimal", "attributes": {}}
        meta = summarizer.summarize_trace_metadata(raw)
        assert meta.trace_id == "minimal"
        assert meta.mission_id is None
        assert meta.reasoning_id is None

    def test_redacts_secrets_in_attributes(self):
        """Secret-like attribute values are redacted."""
        settings = make_settings()
        summarizer = TraceSummarizer(settings=settings)
        raw = make_raw_trace()
        raw["attributes"]["tars.reasoning.root_cause"] = "api_key=sk-123"
        meta = summarizer.summarize_trace_metadata(raw)
        assert "sk-123" not in (meta.root_cause or "")


class TestSummarizeTrace:
    """Test full trace summarization."""

    def test_extracts_stages(self):
        """Extracts stages from spans."""
        settings = make_settings(content_mode=MCPContentMode.METADATA)
        summarizer = TraceSummarizer(settings=settings)
        raw = make_raw_trace()
        summary = summarizer.summarize_trace(raw)
        assert len(summary.stages) == 3
        assert summary.stages[0].name == "reasoning.analyze"

    def test_identifies_root_span(self):
        """Identifies the root span name."""
        settings = make_settings()
        summarizer = TraceSummarizer(settings=settings)
        raw = make_raw_trace()
        summary = summarizer.summarize_trace(raw)
        assert summary.root_span == "reasoning.analyze"

    def test_metadata_mode_no_summary_text(self):
        """Metadata mode does not generate summary text."""
        settings = make_settings(content_mode=MCPContentMode.METADATA)
        summarizer = TraceSummarizer(settings=settings)
        raw = make_raw_trace()
        summary = summarizer.summarize_trace(raw)
        assert summary.summary is None

    def test_summary_mode_generates_text(self):
        """Summary mode generates summary text."""
        settings = make_settings(content_mode=MCPContentMode.SUMMARY)
        summarizer = TraceSummarizer(settings=settings)
        raw = make_raw_trace()
        summary = summarizer.summarize_trace(raw)
        assert summary.summary is not None
        assert len(summary.summary) > 0

    def test_error_stages_detected(self):
        """Error stages are detected and reported."""
        settings = make_settings(content_mode=MCPContentMode.SUMMARY)
        summarizer = TraceSummarizer(settings=settings)
        raw = make_failed_trace()
        summary = summarizer.summarize_trace(raw)
        error_stages = [s for s in summary.stages if s.status == "error"]
        assert len(error_stages) >= 1

    def test_safe_error_extracted(self):
        """Safe error messages are extracted from failed spans."""
        settings = make_settings(content_mode=MCPContentMode.SUMMARY)
        summarizer = TraceSummarizer(settings=settings)
        raw = make_failed_trace(error_message="provider timeout")
        summary = summarizer.summarize_trace(raw)
        error_stages = [s for s in summary.stages if s.safe_error]
        assert len(error_stages) >= 1
        assert "provider timeout" in error_stages[0].safe_error

    def test_duration_preserved(self):
        """Stage durations are preserved."""
        settings = make_settings()
        summarizer = TraceSummarizer(settings=settings)
        raw = make_raw_trace()
        summary = summarizer.summarize_trace(raw)
        durations = [s.duration_ms for s in summary.stages if s.duration_ms]
        assert len(durations) > 0

    def test_handles_empty_spans(self):
        """Handles traces with no spans."""
        settings = make_settings()
        summarizer = TraceSummarizer(settings=settings)
        raw = {"trace_id": "empty", "spans": [], "attributes": {}}
        summary = summarizer.summarize_trace(raw)
        assert summary.trace_id == "empty"
        assert len(summary.stages) == 0

    def test_handles_malformed_spans(self):
        """Handles malformed span data gracefully."""
        settings = make_settings()
        summarizer = TraceSummarizer(settings=settings)
        raw = {
            "trace_id": "malformed",
            "spans": [
                "not_a_dict",
                {"name": "valid", "status": "ok"},
                None,
            ],
            "attributes": {},
        }
        summary = summarizer.summarize_trace(raw)
        # Should skip non-dict spans
        assert len(summary.stages) >= 1

    def test_truncation_marked(self):
        """Overlong summaries are marked as truncated."""
        settings = make_settings(
            content_mode=MCPContentMode.SUMMARY,
            max_summary_chars=50,
        )
        summarizer = TraceSummarizer(settings=settings)
        raw = make_raw_trace()
        summary = summarizer.summarize_trace(raw)
        if summary.summary and len(summary.summary) > 50:
            assert summary.truncated is True

    def test_captured_content_label(self):
        """captured_content reflects the content mode."""
        for mode in (MCPContentMode.METADATA, MCPContentMode.SUMMARY):
            settings = make_settings(content_mode=mode)
            summarizer = TraceSummarizer(settings=settings)
            raw = make_raw_trace()
            summary = summarizer.summarize_trace(raw)
            assert summary.captured_content == mode.value


class TestCompareTraces:
    """Test trace comparison."""

    def test_empty_comparison(self):
        """Empty comparison returns empty response."""
        settings = make_settings()
        summarizer = TraceSummarizer(settings=settings)
        result = summarizer.compare_traces([])
        assert result.trace_ids == []
        assert result.not_an_evaluation is True

    def test_common_attributes_detected(self):
        """Common attributes across traces are detected."""
        settings = make_settings(content_mode=MCPContentMode.SUMMARY)
        summarizer = TraceSummarizer(settings=settings)

        # Create summaries with same prompt version
        from tars.phase8.models import TraceSummary
        summaries = [
            TraceSummary(
                trace_id="t1",
                prompt_version="1.0.0",
                stages=[],
            ),
            TraceSummary(
                trace_id="t2",
                prompt_version="1.0.0",
                stages=[],
            ),
        ]
        result = summarizer.compare_traces(summaries)
        assert result.common_prompt_version == "1.0.0"
        assert result.not_an_evaluation is True

    def test_repeated_failure_detected(self):
        """Repeated failure stages are detected."""
        settings = make_settings(content_mode=MCPContentMode.SUMMARY)
        summarizer = TraceSummarizer(settings=settings)

        from tars.phase8.models import TraceStage, TraceSummary
        summaries = [
            TraceSummary(
                trace_id="t1",
                stages=[
                    TraceStage(name="gemini.generate", status="error"),
                ],
            ),
            TraceSummary(
                trace_id="t2",
                stages=[
                    TraceStage(name="gemini.generate", status="error"),
                ],
            ),
        ]
        result = summarizer.compare_traces(summaries)
        assert result.repeated_failure_stage == "gemini.generate"

    def test_not_an_evaluation_always_true(self):
        """Comparison output always has not_an_evaluation=True."""
        settings = make_settings()
        summarizer = TraceSummarizer(settings=settings)
        result = summarizer.compare_traces([])
        assert result.not_an_evaluation is True

    def test_observed_pattern_generated(self):
        """Observed pattern text is generated."""
        settings = make_settings(content_mode=MCPContentMode.SUMMARY)
        summarizer = TraceSummarizer(settings=settings)

        from tars.phase8.models import TraceSummary
        summaries = [
            TraceSummary(trace_id="t1", prompt_version="1.0.0", stages=[]),
        ]
        result = summarizer.compare_traces(summaries)
        assert result.observed_pattern is not None
