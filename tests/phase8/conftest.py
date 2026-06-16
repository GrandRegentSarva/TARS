"""
Phase 8 Test Fixtures
=====================
Shared fixtures and builders for Phase 8 Phoenix MCP tests.

All tests use fake Phoenix clients and fake tool calls.
No running Phoenix instance, live Gemini, or MCP network services
are required.
"""

from __future__ import annotations

from typing import Any, Optional

import pytest

from tars.phase8.config import MCPContentMode, PhoenixMCPSettings
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
)
from tars.phase8.phoenix_client import FakePhoenixTraceClient
from tars.phase8.summarizer import TraceSummarizer
from tars.phase8.tool_policy import IntrospectionPolicy


# =============================================================================
# Settings Fixtures
# =============================================================================

def make_settings(
    *,
    enabled: bool = True,
    content_mode: MCPContentMode = MCPContentMode.METADATA,
    timeout: float = 5.0,
    default_limit: int = 5,
    max_limit: int = 20,
    max_trace_ids: int = 10,
    max_summary_chars: int = 2000,
    allow_full_dev: bool = False,
) -> PhoenixMCPSettings:
    """Create a PhoenixMCPSettings with test values."""
    settings = PhoenixMCPSettings.__new__(PhoenixMCPSettings)
    settings.ENABLED = enabled
    settings.ENDPOINT = "http://localhost:6006"
    settings.TIMEOUT_SECONDS = timeout
    settings.CONTENT_MODE = content_mode
    settings.DEFAULT_LIMIT = default_limit
    settings.MAX_LIMIT = max_limit
    settings.MAX_TRACE_IDS = max_trace_ids
    settings.MAX_SUMMARY_CHARS = max_summary_chars
    settings.ALLOW_FULL_DEV_CONTENT = allow_full_dev
    return settings


@pytest.fixture
def enabled_settings() -> PhoenixMCPSettings:
    """Create enabled Phoenix MCP settings with metadata mode."""
    return make_settings(enabled=True, content_mode=MCPContentMode.METADATA)


@pytest.fixture
def summary_settings() -> PhoenixMCPSettings:
    """Create enabled Phoenix MCP settings with summary mode."""
    return make_settings(enabled=True, content_mode=MCPContentMode.SUMMARY)


@pytest.fixture
def disabled_settings() -> PhoenixMCPSettings:
    """Create disabled Phoenix MCP settings."""
    return make_settings(enabled=False, content_mode=MCPContentMode.DISABLED)


@pytest.fixture
def full_dev_settings() -> PhoenixMCPSettings:
    """Create enabled Phoenix MCP settings with full_dev mode."""
    return make_settings(
        enabled=True,
        content_mode=MCPContentMode.FULL_DEV,
        allow_full_dev=True,
    )


# =============================================================================
# Trace Data Builders
# =============================================================================

def make_raw_trace(
    *,
    trace_id: str = "trace_abc123",
    mission_id: str = "mission_test_001",
    incident_id: str = "inc_test123",
    incident_type: str = "navigation_instability",
    reasoning_id: str = "reason_test001",
    root_cause: str = "gps_interference",
    confidence: float = 0.72,
    prompt_version: str = "1.0.0",
    model: str = "gemini-2.5-flash",
    outcome: str = "success",
    duration_ms: int = 1280,
    spans: Optional[list[dict[str, Any]]] = None,
) -> dict[str, Any]:
    """Build a raw trace dict matching Phoenix API response structure."""
    default_spans = [
        {
            "name": "reasoning.analyze",
            "status": {"status_code": "OK", "description": ""},
            "duration_ms": duration_ms,
            "start_time": "2026-06-15T10:30:00Z",
            "end_time": "2026-06-15T10:30:01.280Z",
            "attributes": {
                "tars.mission.id": mission_id,
                "tars.incident.id": incident_id,
                "tars.incident.type": incident_type,
                "tars.reasoning.id": reasoning_id,
                "tars.reasoning.root_cause": root_cause,
                "tars.reasoning.confidence": confidence,
                "tars.reasoning.prompt_version": prompt_version,
                "tars.reasoning.outcome": outcome,
                "llm.model_name": model,
                "openinference.span.kind": "CHAIN",
            },
        },
        {
            "name": "phase4.get_incident",
            "status": {"status_code": "OK", "description": ""},
            "duration_ms": 42,
            "start_time": "2026-06-15T10:30:00Z",
            "end_time": "2026-06-15T10:30:00.042Z",
            "attributes": {},
        },
        {
            "name": "gemini.generate",
            "status": {"status_code": "OK", "description": ""},
            "duration_ms": 1100,
            "start_time": "2026-06-15T10:30:00.050Z",
            "end_time": "2026-06-15T10:30:01.150Z",
            "attributes": {
                "llm.model_name": model,
                "tars.reasoning.prompt_version": prompt_version,
            },
        },
    ]

    return {
        "trace_id": trace_id,
        "spans": spans if spans is not None else default_spans,
        "attributes": {
            "tars.mission.id": mission_id,
            "tars.incident.id": incident_id,
            "tars.incident.type": incident_type,
            "tars.reasoning.id": reasoning_id,
            "tars.reasoning.root_cause": root_cause,
            "tars.reasoning.confidence": confidence,
            "tars.reasoning.prompt_version": prompt_version,
            "tars.reasoning.outcome": outcome,
            "llm.model_name": model,
        },
        "duration_ms": duration_ms,
        "created_at": "2026-06-15T10:30:00Z",
    }


def make_failed_trace(
    *,
    trace_id: str = "trace_fail001",
    incident_type: str = "navigation_instability",
    root_cause: str = "gps_interference",
    error_message: str = "provider timeout",
) -> dict[str, Any]:
    """Build a raw trace with a failed gemini.generate stage."""
    return make_raw_trace(
        trace_id=trace_id,
        incident_type=incident_type,
        root_cause=root_cause,
        outcome="failed",
        spans=[
            {
                "name": "reasoning.analyze",
                "status": {"status_code": "ERROR", "description": error_message},
                "duration_ms": 1200,
                "start_time": "2026-06-15T10:30:00Z",
                "end_time": "2026-06-15T10:30:01.200Z",
                "attributes": {
                    "tars.mission.id": "mission_test_001",
                    "tars.incident.id": "inc_test123",
                    "tars.incident.type": incident_type,
                    "tars.reasoning.id": "reason_fail001",
                    "tars.reasoning.root_cause": root_cause,
                    "tars.reasoning.confidence": 0.0,
                    "tars.reasoning.prompt_version": "1.0.0",
                    "tars.reasoning.outcome": "failed",
                    "llm.model_name": "gemini-2.5-flash",
                },
            },
            {
                "name": "phase4.get_incident",
                "status": {"status_code": "OK", "description": ""},
                "duration_ms": 42,
                "start_time": "2026-06-15T10:30:00Z",
                "end_time": "2026-06-15T10:30:00.042Z",
                "attributes": {},
            },
            {
                "name": "gemini.generate",
                "status": {"status_code": "ERROR", "description": error_message},
                "duration_ms": 1100,
                "start_time": "2026-06-15T10:30:00.050Z",
                "end_time": "2026-06-15T10:30:01.150Z",
                "attributes": {
                    "llm.model_name": "gemini-2.5-flash",
                },
                "events": [
                    {
                        "name": "exception",
                        "attributes": {
                            "exception.message": error_message,
                        },
                    },
                ],
            },
        ],
    )


@pytest.fixture
def fake_client() -> FakePhoenixTraceClient:
    """Create a fake Phoenix client with sample traces."""
    client = FakePhoenixTraceClient()
    client.add_trace(make_raw_trace())
    client.add_trace(make_raw_trace(
        trace_id="trace_def456",
        reasoning_id="reason_test002",
        confidence=0.85,
        outcome="success",
    ))
    client.add_trace(make_failed_trace())
    return client


@pytest.fixture
def empty_client() -> FakePhoenixTraceClient:
    """Create a fake Phoenix client with no traces."""
    return FakePhoenixTraceClient()


@pytest.fixture
def unavailable_client() -> FakePhoenixTraceClient:
    """Create a fake Phoenix client that simulates unavailability."""
    return FakePhoenixTraceClient(unavailable=True)


@pytest.fixture
def failing_client() -> FakePhoenixTraceClient:
    """Create a fake Phoenix client that always fails."""
    return FakePhoenixTraceClient(fail=True, fail_message="Test failure")
