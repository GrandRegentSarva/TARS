"""
Tests for Phase 6 Reasoning Traces
====================================
Integration tests verifying the full span hierarchy produced by
instrumented Phase 5 service and provider.

All tests use an in-memory span exporter and fake provider.
No running Phoenix, Redis, or Gemini credentials are required.

Test categories:
- Successful analysis trace structure
- Cached analysis traces
- Failure traces (provider, Phase 4, validation, persistence)
- Content policy (full vs metadata mode)
- Parent-child span relationships
- Attribute correctness
"""

from __future__ import annotations

import socket
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode

from tars.phase5.incident_client import IncidentClient
from tars.phase5.models import ReasoningAnalysis, ReasoningResult
from tars.phase5.provider import FakeReasoningProvider
from tars.phase5.service import ReasoningService
from tars.phase5.store import ReasoningStore
from tars.phase6 import attributes as attrs
from tars.phase6.config import ContentMode, PhoenixSettings
from tars.phase6.tracing import init_tracing, reset_tracing

from .conftest import make_battery_incident, make_incident


# =============================================================================
# Redis Helpers
# =============================================================================

def _redis_is_reachable(host: str = "localhost", port: int = 6379) -> bool:
    try:
        with socket.create_connection((host, port), timeout=2.0):
            return True
    except OSError:
        return False


_TEST_REDIS_URL = "redis://localhost:6379/15"

requires_redis = pytest.mark.skipif(
    not _redis_is_reachable(),
    reason="Redis not available on localhost:6379",
)


# =============================================================================
# Fixtures
# =============================================================================

@pytest_asyncio.fixture
async def traced_service(
    tracing_settings_enabled, in_memory_exporter
):
    """
    Create a fully instrumented service with in-memory tracing.

    Requires Redis on localhost:6379 (DB 15).
    """
    if not _redis_is_reachable():
        pytest.skip("Redis not available on localhost:6379")

    # Initialize tracing with in-memory exporter
    init_tracing(
        settings=tracing_settings_enabled,
        exporter=in_memory_exporter,
    )

    store = ReasoningStore(redis_url=_TEST_REDIS_URL)
    await store.connect()

    mock_client = AsyncMock(spec=IncidentClient)
    fake_provider = FakeReasoningProvider()

    service = ReasoningService(
        store=store,
        incident_client=mock_client,
        provider=fake_provider,
    )

    yield service, mock_client, fake_provider, store, in_memory_exporter

    await store.redis.flushdb()
    await store.close()


@pytest_asyncio.fixture
async def traced_service_metadata(
    tracing_settings_metadata,
):
    """
    Create a service with metadata-only tracing.

    Patches the module-level phoenix_settings so that the provider's
    _get_config() returns the metadata settings instead of the global
    singleton.
    """
    if not _redis_is_reachable():
        pytest.skip("Redis not available on localhost:6379")

    exporter = InMemorySpanExporter()
    init_tracing(
        settings=tracing_settings_metadata,
        exporter=exporter,
    )

    store = ReasoningStore(redis_url=_TEST_REDIS_URL)
    await store.connect()

    mock_client = AsyncMock(spec=IncidentClient)
    fake_provider = FakeReasoningProvider()

    service = ReasoningService(
        store=store,
        incident_client=mock_client,
        provider=fake_provider,
    )

    with patch(
        "tars.phase6.config.phoenix_settings", tracing_settings_metadata
    ):
        yield service, mock_client, fake_provider, store, exporter

    await store.redis.flushdb()
    await store.close()


def _get_spans_by_name(exporter, name):
    """Get all finished spans with a given name."""
    return [s for s in exporter.get_finished_spans() if s.name == name]


def _get_span_by_name(exporter, name):
    """Get exactly one span with a given name, or fail."""
    spans = _get_spans_by_name(exporter, name)
    assert len(spans) == 1, (
        f"Expected 1 span named '{name}', got {len(spans)}: "
        f"{[s.name for s in exporter.get_finished_spans()]}"
    )
    return spans[0]


# =============================================================================
# Successful Analysis Trace Tests
# =============================================================================

@requires_redis
class TestSuccessfulAnalysisTrace:
    """Test trace structure for a successful reasoning analysis."""

    @pytest.mark.asyncio
    async def test_emits_root_reasoning_span(self, traced_service):
        service, mock_client, provider, store, exporter = traced_service
        incident = make_incident()
        mock_client.get_incident = AsyncMock(return_value=incident)

        await service.analyze_incident("test_mission", "inc_test123")

        root = _get_span_by_name(exporter, attrs.SPAN_REASONING_ANALYZE)
        assert root is not None

    @pytest.mark.asyncio
    async def test_root_span_has_mission_id(self, traced_service):
        service, mock_client, provider, store, exporter = traced_service
        incident = make_incident()
        mock_client.get_incident = AsyncMock(return_value=incident)

        await service.analyze_incident("test_mission", "inc_test123")

        root = _get_span_by_name(exporter, attrs.SPAN_REASONING_ANALYZE)
        assert root.attributes[attrs.TARS_MISSION_ID] == "test_mission"

    @pytest.mark.asyncio
    async def test_root_span_has_incident_id(self, traced_service):
        service, mock_client, provider, store, exporter = traced_service
        incident = make_incident()
        mock_client.get_incident = AsyncMock(return_value=incident)

        await service.analyze_incident("test_mission", "inc_test123")

        root = _get_span_by_name(exporter, attrs.SPAN_REASONING_ANALYZE)
        assert root.attributes[attrs.TARS_INCIDENT_ID] == "inc_test123"

    @pytest.mark.asyncio
    async def test_root_span_has_incident_type_after_retrieval(
        self, traced_service
    ):
        service, mock_client, provider, store, exporter = traced_service
        incident = make_incident()
        mock_client.get_incident = AsyncMock(return_value=incident)

        await service.analyze_incident("test_mission", "inc_test123")

        root = _get_span_by_name(exporter, attrs.SPAN_REASONING_ANALYZE)
        assert root.attributes[attrs.TARS_INCIDENT_TYPE] == (
            "navigation_instability"
        )

    @pytest.mark.asyncio
    async def test_root_span_has_incident_severity(self, traced_service):
        service, mock_client, provider, store, exporter = traced_service
        incident = make_incident()
        mock_client.get_incident = AsyncMock(return_value=incident)

        await service.analyze_incident("test_mission", "inc_test123")

        root = _get_span_by_name(exporter, attrs.SPAN_REASONING_ANALYZE)
        assert root.attributes[attrs.TARS_INCIDENT_SEVERITY] == "high"

    @pytest.mark.asyncio
    async def test_root_span_has_reasoning_id(self, traced_service):
        service, mock_client, provider, store, exporter = traced_service
        incident = make_incident()
        mock_client.get_incident = AsyncMock(return_value=incident)

        result = await service.analyze_incident(
            "test_mission", "inc_test123"
        )

        root = _get_span_by_name(exporter, attrs.SPAN_REASONING_ANALYZE)
        assert root.attributes[attrs.TARS_REASONING_ID] == (
            result.reasoning_id
        )

    @pytest.mark.asyncio
    async def test_root_span_has_root_cause(self, traced_service):
        service, mock_client, provider, store, exporter = traced_service
        incident = make_incident()
        mock_client.get_incident = AsyncMock(return_value=incident)

        await service.analyze_incident("test_mission", "inc_test123")

        root = _get_span_by_name(exporter, attrs.SPAN_REASONING_ANALYZE)
        assert root.attributes[attrs.TARS_REASONING_ROOT_CAUSE] == (
            "gps_interference"
        )

    @pytest.mark.asyncio
    async def test_root_span_has_confidence(self, traced_service):
        service, mock_client, provider, store, exporter = traced_service
        incident = make_incident()
        mock_client.get_incident = AsyncMock(return_value=incident)

        await service.analyze_incident("test_mission", "inc_test123")

        root = _get_span_by_name(exporter, attrs.SPAN_REASONING_ANALYZE)
        confidence = root.attributes[attrs.TARS_REASONING_CONFIDENCE]
        assert 0.0 <= confidence <= 1.0

    @pytest.mark.asyncio
    async def test_root_span_has_prompt_version(self, traced_service):
        service, mock_client, provider, store, exporter = traced_service
        incident = make_incident()
        mock_client.get_incident = AsyncMock(return_value=incident)

        await service.analyze_incident("test_mission", "inc_test123")

        root = _get_span_by_name(exporter, attrs.SPAN_REASONING_ANALYZE)
        assert root.attributes[attrs.TARS_REASONING_PROMPT_VERSION] == "1.0.0"

    @pytest.mark.asyncio
    async def test_root_span_advisory_only(self, traced_service):
        service, mock_client, provider, store, exporter = traced_service
        incident = make_incident()
        mock_client.get_incident = AsyncMock(return_value=incident)

        await service.analyze_incident("test_mission", "inc_test123")

        root = _get_span_by_name(exporter, attrs.SPAN_REASONING_ANALYZE)
        assert root.attributes[attrs.TARS_REASONING_ADVISORY_ONLY] is True

    @pytest.mark.asyncio
    async def test_root_span_outcome_success(self, traced_service):
        service, mock_client, provider, store, exporter = traced_service
        incident = make_incident()
        mock_client.get_incident = AsyncMock(return_value=incident)

        await service.analyze_incident("test_mission", "inc_test123")

        root = _get_span_by_name(exporter, attrs.SPAN_REASONING_ANALYZE)
        assert root.attributes[attrs.TARS_REASONING_OUTCOME] == (
            attrs.OUTCOME_SUCCESS
        )

    @pytest.mark.asyncio
    async def test_root_span_not_cached(self, traced_service):
        service, mock_client, provider, store, exporter = traced_service
        incident = make_incident()
        mock_client.get_incident = AsyncMock(return_value=incident)

        await service.analyze_incident("test_mission", "inc_test123")

        root = _get_span_by_name(exporter, attrs.SPAN_REASONING_ANALYZE)
        assert root.attributes[attrs.TARS_REASONING_CACHED] is False


# =============================================================================
# Span Hierarchy Tests
# =============================================================================

@requires_redis
class TestSpanHierarchy:
    """Test parent-child span relationships."""

    @pytest.mark.asyncio
    async def test_all_expected_spans_present(self, traced_service):
        service, mock_client, provider, store, exporter = traced_service
        incident = make_incident()
        mock_client.get_incident = AsyncMock(return_value=incident)

        await service.analyze_incident("test_mission", "inc_test123")

        span_names = {s.name for s in exporter.get_finished_spans()}
        expected = {
            attrs.SPAN_REASONING_ANALYZE,
            attrs.SPAN_REASONING_BUILD_PROMPT,
            attrs.SPAN_PHASE4_GET_INCIDENT,
            attrs.SPAN_GEMINI_GENERATE,
            attrs.SPAN_REASONING_VALIDATE,
            attrs.SPAN_REASONING_PERSIST,
        }
        assert expected.issubset(span_names), (
            f"Missing spans: {expected - span_names}"
        )

    @pytest.mark.asyncio
    async def test_child_spans_have_root_parent(self, traced_service):
        service, mock_client, provider, store, exporter = traced_service
        incident = make_incident()
        mock_client.get_incident = AsyncMock(return_value=incident)

        await service.analyze_incident("test_mission", "inc_test123")

        root = _get_span_by_name(exporter, attrs.SPAN_REASONING_ANALYZE)
        root_ctx = root.context

        child_names = [
            attrs.SPAN_PHASE4_GET_INCIDENT,
            attrs.SPAN_REASONING_VALIDATE,
            attrs.SPAN_REASONING_PERSIST,
        ]

        for name in child_names:
            child = _get_span_by_name(exporter, name)
            assert child.parent is not None, (
                f"Span '{name}' has no parent"
            )
            assert child.parent.trace_id == root_ctx.trace_id, (
                f"Span '{name}' not in same trace as root"
            )

    @pytest.mark.asyncio
    async def test_gemini_span_in_same_trace(self, traced_service):
        service, mock_client, provider, store, exporter = traced_service
        incident = make_incident()
        mock_client.get_incident = AsyncMock(return_value=incident)

        await service.analyze_incident("test_mission", "inc_test123")

        root = _get_span_by_name(exporter, attrs.SPAN_REASONING_ANALYZE)
        gemini = _get_span_by_name(exporter, attrs.SPAN_GEMINI_GENERATE)

        assert gemini.parent is not None
        assert gemini.parent.trace_id == root.context.trace_id


# =============================================================================
# Gemini Span Attribute Tests
# =============================================================================

@requires_redis
class TestGeminiSpanAttributes:
    """Test OpenInference LLM attributes on the Gemini span."""

    @pytest.mark.asyncio
    async def test_gemini_span_has_model_name(self, traced_service):
        service, mock_client, provider, store, exporter = traced_service
        incident = make_incident()
        mock_client.get_incident = AsyncMock(return_value=incident)

        await service.analyze_incident("test_mission", "inc_test123")

        gemini = _get_span_by_name(exporter, attrs.SPAN_GEMINI_GENERATE)
        assert gemini.attributes[attrs.OI_LLM_MODEL_NAME] == (
            "fake-gemini-test"
        )

    @pytest.mark.asyncio
    async def test_gemini_span_has_provider(self, traced_service):
        service, mock_client, provider, store, exporter = traced_service
        incident = make_incident()
        mock_client.get_incident = AsyncMock(return_value=incident)

        await service.analyze_incident("test_mission", "inc_test123")

        gemini = _get_span_by_name(exporter, attrs.SPAN_GEMINI_GENERATE)
        assert gemini.attributes[attrs.OI_LLM_PROVIDER] == "google"

    @pytest.mark.asyncio
    async def test_gemini_span_has_prompt_version(self, traced_service):
        service, mock_client, provider, store, exporter = traced_service
        incident = make_incident()
        mock_client.get_incident = AsyncMock(return_value=incident)

        await service.analyze_incident("test_mission", "inc_test123")

        gemini = _get_span_by_name(exporter, attrs.SPAN_GEMINI_GENERATE)
        assert gemini.attributes[attrs.TARS_REASONING_PROMPT_VERSION] == (
            "1.0.0"
        )

    @pytest.mark.asyncio
    async def test_gemini_span_has_llm_span_kind(self, traced_service):
        service, mock_client, provider, store, exporter = traced_service
        incident = make_incident()
        mock_client.get_incident = AsyncMock(return_value=incident)

        await service.analyze_incident("test_mission", "inc_test123")

        gemini = _get_span_by_name(exporter, attrs.SPAN_GEMINI_GENERATE)
        assert gemini.attributes[attrs.OI_OPENINFERENCE_SPAN_KIND] == (
            attrs.OI_SPAN_KIND_LLM
        )


# =============================================================================
# Cached Analysis Trace Tests
# =============================================================================

@requires_redis
class TestCachedAnalysisTrace:
    """Test trace behavior for cached (overwrite=false) analyses."""

    @pytest.mark.asyncio
    async def test_cached_analysis_has_cached_true(self, traced_service):
        service, mock_client, provider, store, exporter = traced_service
        incident = make_incident()
        mock_client.get_incident = AsyncMock(return_value=incident)

        # First analysis
        await service.analyze_incident(
            "test_mission", "inc_test123", overwrite=True
        )
        exporter.clear()

        # Second with overwrite=false
        await service.analyze_incident(
            "test_mission", "inc_test123", overwrite=False
        )

        root = _get_span_by_name(exporter, attrs.SPAN_REASONING_ANALYZE)
        assert root.attributes[attrs.TARS_REASONING_CACHED] is True

    @pytest.mark.asyncio
    async def test_cached_analysis_outcome_cached(self, traced_service):
        service, mock_client, provider, store, exporter = traced_service
        incident = make_incident()
        mock_client.get_incident = AsyncMock(return_value=incident)

        await service.analyze_incident(
            "test_mission", "inc_test123", overwrite=True
        )
        exporter.clear()

        await service.analyze_incident(
            "test_mission", "inc_test123", overwrite=False
        )

        root = _get_span_by_name(exporter, attrs.SPAN_REASONING_ANALYZE)
        assert root.attributes[attrs.TARS_REASONING_OUTCOME] == (
            attrs.OUTCOME_CACHED
        )

    @pytest.mark.asyncio
    async def test_cached_analysis_has_cache_lookup_span(
        self, traced_service
    ):
        service, mock_client, provider, store, exporter = traced_service
        incident = make_incident()
        mock_client.get_incident = AsyncMock(return_value=incident)

        await service.analyze_incident(
            "test_mission", "inc_test123", overwrite=True
        )
        exporter.clear()

        await service.analyze_incident(
            "test_mission", "inc_test123", overwrite=False
        )

        cache_span = _get_span_by_name(
            exporter, attrs.SPAN_REASONING_CACHE_LOOKUP
        )
        assert cache_span.attributes.get("cache.hit") is True

    @pytest.mark.asyncio
    async def test_cached_analysis_no_gemini_span(self, traced_service):
        service, mock_client, provider, store, exporter = traced_service
        incident = make_incident()
        mock_client.get_incident = AsyncMock(return_value=incident)

        await service.analyze_incident(
            "test_mission", "inc_test123", overwrite=True
        )
        exporter.clear()

        await service.analyze_incident(
            "test_mission", "inc_test123", overwrite=False
        )

        gemini_spans = _get_spans_by_name(
            exporter, attrs.SPAN_GEMINI_GENERATE
        )
        assert len(gemini_spans) == 0


# =============================================================================
# Content Policy Tests
# =============================================================================

@requires_redis
class TestContentPolicyFull:
    """Test full content mode captures prompt and response."""

    @pytest.mark.asyncio
    async def test_full_mode_captures_prompt(self, traced_service):
        service, mock_client, provider, store, exporter = traced_service
        incident = make_incident()
        mock_client.get_incident = AsyncMock(return_value=incident)

        await service.analyze_incident("test_mission", "inc_test123")

        gemini = _get_span_by_name(exporter, attrs.SPAN_GEMINI_GENERATE)
        input_value = gemini.attributes.get(attrs.OI_INPUT_VALUE, "")
        assert "navigation_instability" in input_value
        assert "Prompt version:" in input_value

    @pytest.mark.asyncio
    async def test_full_mode_captures_response(self, traced_service):
        service, mock_client, provider, store, exporter = traced_service
        incident = make_incident()
        mock_client.get_incident = AsyncMock(return_value=incident)

        await service.analyze_incident("test_mission", "inc_test123")

        gemini = _get_span_by_name(exporter, attrs.SPAN_GEMINI_GENERATE)
        output_value = gemini.attributes.get(attrs.OI_OUTPUT_VALUE, "")
        assert "gps_interference" in output_value

    @pytest.mark.asyncio
    async def test_full_mode_has_mime_types(self, traced_service):
        service, mock_client, provider, store, exporter = traced_service
        incident = make_incident()
        mock_client.get_incident = AsyncMock(return_value=incident)

        await service.analyze_incident("test_mission", "inc_test123")

        gemini = _get_span_by_name(exporter, attrs.SPAN_GEMINI_GENERATE)
        assert gemini.attributes.get(attrs.OI_INPUT_MIME_TYPE) == (
            "text/plain"
        )
        assert gemini.attributes.get(attrs.OI_OUTPUT_MIME_TYPE) == (
            "application/json"
        )


@requires_redis
class TestContentPolicyMetadata:
    """Test metadata mode excludes prompt and response bodies."""

    @pytest.mark.asyncio
    async def test_metadata_mode_no_prompt(self, traced_service_metadata):
        service, mock_client, provider, store, exporter = (
            traced_service_metadata
        )
        incident = make_incident()
        mock_client.get_incident = AsyncMock(return_value=incident)

        await service.analyze_incident("test_mission", "inc_test123")

        gemini = _get_span_by_name(exporter, attrs.SPAN_GEMINI_GENERATE)
        assert attrs.OI_INPUT_VALUE not in gemini.attributes

    @pytest.mark.asyncio
    async def test_metadata_mode_no_response(self, traced_service_metadata):
        service, mock_client, provider, store, exporter = (
            traced_service_metadata
        )
        incident = make_incident()
        mock_client.get_incident = AsyncMock(return_value=incident)

        await service.analyze_incident("test_mission", "inc_test123")

        gemini = _get_span_by_name(exporter, attrs.SPAN_GEMINI_GENERATE)
        assert attrs.OI_OUTPUT_VALUE not in gemini.attributes

    @pytest.mark.asyncio
    async def test_metadata_mode_still_has_model(
        self, traced_service_metadata
    ):
        service, mock_client, provider, store, exporter = (
            traced_service_metadata
        )
        incident = make_incident()
        mock_client.get_incident = AsyncMock(return_value=incident)

        await service.analyze_incident("test_mission", "inc_test123")

        gemini = _get_span_by_name(exporter, attrs.SPAN_GEMINI_GENERATE)
        assert gemini.attributes[attrs.OI_LLM_MODEL_NAME] == (
            "fake-gemini-test"
        )


# =============================================================================
# Content Safety Tests
# =============================================================================

@requires_redis
class TestContentSafety:
    """Test that prohibited content never appears in traces."""

    @pytest.mark.asyncio
    async def test_no_raw_telemetry_in_traces(self, traced_service):
        service, mock_client, provider, store, exporter = traced_service
        incident = make_incident()
        mock_client.get_incident = AsyncMock(return_value=incident)

        await service.analyze_incident("test_mission", "inc_test123")

        for span in exporter.get_finished_spans():
            for key, value in span.attributes.items():
                # Raw telemetry fields should never appear in keys or values
                assert "gps_lat" not in key
                assert "gps_lon" not in key
                assert "imu_raw" not in key
                if isinstance(value, str):
                    assert "gps_lat" not in value
                    assert "gps_lon" not in value
                    assert "imu_raw" not in value

    @pytest.mark.asyncio
    async def test_no_credentials_in_traces(self, traced_service):
        service, mock_client, provider, store, exporter = traced_service
        incident = make_incident()
        mock_client.get_incident = AsyncMock(return_value=incident)

        await service.analyze_incident("test_mission", "inc_test123")

        for span in exporter.get_finished_spans():
            for key, value in span.attributes.items():
                # Credentials should never appear in keys or values
                assert "api_key" not in key.lower()
                assert "authorization" not in key.lower()
                assert "password" not in key.lower()
                assert "secret" not in key.lower()
                if isinstance(value, str):
                    assert "api_key" not in value.lower()
                    assert "authorization" not in value.lower()
                    assert "password" not in value.lower()
                    assert "secret" not in value.lower()


# =============================================================================
# Failure Trace Tests
# =============================================================================

@requires_redis
class TestFailureTraces:
    """Test trace behavior when reasoning stages fail."""

    @pytest.mark.asyncio
    async def test_provider_failure_marks_root_error(self, traced_service):
        service, mock_client, provider, store, exporter = traced_service
        incident = make_incident()
        mock_client.get_incident = AsyncMock(return_value=incident)

        # Replace with failing provider
        service._provider = FakeReasoningProvider(
            fail=True, fail_message="Provider error"
        )

        with pytest.raises(ValueError, match="Provider error"):
            await service.analyze_incident(
                "test_mission", "inc_test123"
            )

        root = _get_span_by_name(exporter, attrs.SPAN_REASONING_ANALYZE)
        assert root.status.status_code == StatusCode.ERROR
        assert root.attributes[attrs.TARS_REASONING_OUTCOME] == (
            attrs.OUTCOME_FAILED
        )

    @pytest.mark.asyncio
    async def test_provider_failure_marks_gemini_error(self, traced_service):
        service, mock_client, provider, store, exporter = traced_service
        incident = make_incident()
        mock_client.get_incident = AsyncMock(return_value=incident)

        service._provider = FakeReasoningProvider(
            fail=True, fail_message="Provider error"
        )

        with pytest.raises(ValueError):
            await service.analyze_incident(
                "test_mission", "inc_test123"
            )

        gemini = _get_span_by_name(exporter, attrs.SPAN_GEMINI_GENERATE)
        assert gemini.status.status_code == StatusCode.ERROR

    @pytest.mark.asyncio
    async def test_phase4_failure_marks_incident_span_error(
        self, traced_service
    ):
        service, mock_client, provider, store, exporter = traced_service

        import httpx

        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.json.return_value = {}
        mock_client.get_incident = AsyncMock(
            side_effect=httpx.HTTPStatusError(
                "Not Found",
                request=MagicMock(),
                response=mock_response,
            )
        )

        with pytest.raises(httpx.HTTPStatusError):
            await service.analyze_incident(
                "test_mission", "inc_missing"
            )

        incident_span = _get_span_by_name(
            exporter, attrs.SPAN_PHASE4_GET_INCIDENT
        )
        assert incident_span.status.status_code == StatusCode.ERROR

    @pytest.mark.asyncio
    async def test_phase4_failure_marks_root_error(self, traced_service):
        service, mock_client, provider, store, exporter = traced_service

        import httpx

        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_client.get_incident = AsyncMock(
            side_effect=httpx.HTTPStatusError(
                "Not Found",
                request=MagicMock(),
                response=mock_response,
            )
        )

        with pytest.raises(httpx.HTTPStatusError):
            await service.analyze_incident(
                "test_mission", "inc_missing"
            )

        root = _get_span_by_name(exporter, attrs.SPAN_REASONING_ANALYZE)
        assert root.status.status_code == StatusCode.ERROR
        assert root.attributes[attrs.TARS_REASONING_OUTCOME] == (
            attrs.OUTCOME_FAILED
        )

    @pytest.mark.asyncio
    async def test_phase4_failure_no_gemini_span(self, traced_service):
        service, mock_client, provider, store, exporter = traced_service

        import httpx

        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_client.get_incident = AsyncMock(
            side_effect=httpx.HTTPStatusError(
                "Server Error",
                request=MagicMock(),
                response=mock_response,
            )
        )

        with pytest.raises(httpx.HTTPStatusError):
            await service.analyze_incident(
                "test_mission", "inc_error"
            )

        gemini_spans = _get_spans_by_name(
            exporter, attrs.SPAN_GEMINI_GENERATE
        )
        assert len(gemini_spans) == 0

    @pytest.mark.asyncio
    async def test_failed_analysis_not_persisted(self, traced_service):
        service, mock_client, provider, store, exporter = traced_service
        incident = make_incident()
        mock_client.get_incident = AsyncMock(return_value=incident)

        service._provider = FakeReasoningProvider(
            fail=True, fail_message="Provider error"
        )

        with pytest.raises(ValueError):
            await service.analyze_incident(
                "test_mission", "inc_test123"
            )

        persisted = await store.get_analysis("test_mission", "inc_test123")
        assert persisted is None


# =============================================================================
# Overwrite Attribute Tests
# =============================================================================

@requires_redis
class TestOverwriteAttribute:
    """Test that overwrite flag is recorded in traces."""

    @pytest.mark.asyncio
    async def test_overwrite_true_recorded(self, traced_service):
        service, mock_client, provider, store, exporter = traced_service
        incident = make_incident()
        mock_client.get_incident = AsyncMock(return_value=incident)

        await service.analyze_incident(
            "test_mission", "inc_test123", overwrite=True
        )

        root = _get_span_by_name(exporter, attrs.SPAN_REASONING_ANALYZE)
        assert root.attributes[attrs.TARS_REASONING_OVERWRITE] is True

    @pytest.mark.asyncio
    async def test_overwrite_false_recorded(self, traced_service):
        service, mock_client, provider, store, exporter = traced_service
        incident = make_incident()
        mock_client.get_incident = AsyncMock(return_value=incident)

        # No existing analysis, so it will proceed to analyze
        await service.analyze_incident(
            "test_mission", "inc_test123", overwrite=False
        )

        root = _get_span_by_name(exporter, attrs.SPAN_REASONING_ANALYZE)
        assert root.attributes[attrs.TARS_REASONING_OVERWRITE] is False


# =============================================================================
# Tracing Failure Isolation Tests
# =============================================================================

class TestTracingFailureIsolation:
    """Test that tracing failures never affect reasoning results."""

    @pytest.mark.asyncio
    async def test_reasoning_works_without_tracing(self):
        """Phase 5 service works when Phase 6 tracing is not initialized."""
        if not _redis_is_reachable():
            pytest.skip("Redis not available on localhost:6379")

        # Don't initialize tracing at all
        store = ReasoningStore(redis_url=_TEST_REDIS_URL)
        await store.connect()

        mock_client = AsyncMock(spec=IncidentClient)
        incident = make_incident()
        mock_client.get_incident = AsyncMock(return_value=incident)

        fake_provider = FakeReasoningProvider()
        service = ReasoningService(
            store=store,
            incident_client=mock_client,
            provider=fake_provider,
        )

        result = await service.analyze_incident(
            "test_mission", "inc_test123"
        )

        assert result.root_cause == "gps_interference"
        assert result.advisory_only is True

        await store.redis.flushdb()
        await store.close()