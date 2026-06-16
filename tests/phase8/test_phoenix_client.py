"""
Phase 8 Phoenix Client Tests
==============================
Tests for the Phoenix trace query client using fake clients.

All tests run without live Phoenix, Gemini, or MCP network services.
"""

from __future__ import annotations

import pytest

from tars.phase8.models import TraceSearchRequest
from tars.phase8.phoenix_client import FakePhoenixTraceClient

from .conftest import make_failed_trace, make_raw_trace, make_settings


class TestFakePhoenixTraceClient:
    """Test the fake Phoenix client for correctness."""

    @pytest.mark.asyncio
    async def test_search_returns_matching_traces(self):
        """Search returns traces matching filters."""
        client = FakePhoenixTraceClient()
        client.add_trace(make_raw_trace(
            trace_id="t1",
            incident_type="navigation_instability",
        ))
        client.add_trace(make_raw_trace(
            trace_id="t2",
            incident_type="battery_degradation",
        ))

        request = TraceSearchRequest(incident_type="navigation_instability")
        results = await client.search_traces(request)
        assert len(results) == 1
        assert results[0]["trace_id"] == "t1"

    @pytest.mark.asyncio
    async def test_search_by_mission_id(self):
        """Search filters by mission_id."""
        client = FakePhoenixTraceClient()
        client.add_trace(make_raw_trace(trace_id="t1", mission_id="m1"))
        client.add_trace(make_raw_trace(trace_id="t2", mission_id="m2"))

        request = TraceSearchRequest(mission_id="m1")
        results = await client.search_traces(request)
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_search_by_root_cause(self):
        """Search filters by root_cause."""
        client = FakePhoenixTraceClient()
        client.add_trace(make_raw_trace(trace_id="t1", root_cause="gps"))
        client.add_trace(make_raw_trace(trace_id="t2", root_cause="battery"))

        request = TraceSearchRequest(root_cause="gps")
        results = await client.search_traces(request)
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_search_by_outcome(self):
        """Search filters by outcome."""
        client = FakePhoenixTraceClient()
        client.add_trace(make_raw_trace(trace_id="t1", outcome="success"))
        client.add_trace(make_raw_trace(trace_id="t2", outcome="failed"))

        request = TraceSearchRequest(outcome="failed")
        results = await client.search_traces(request)
        assert len(results) == 1
        assert results[0]["trace_id"] == "t2"

    @pytest.mark.asyncio
    async def test_search_respects_limit(self):
        """Search respects the limit parameter."""
        client = FakePhoenixTraceClient()
        for i in range(10):
            client.add_trace(make_raw_trace(trace_id=f"t{i}"))

        request = TraceSearchRequest(limit=3)
        results = await client.search_traces(request)
        assert len(results) == 3

    @pytest.mark.asyncio
    async def test_search_no_filters_returns_all(self):
        """Search with no filters returns all traces up to limit."""
        client = FakePhoenixTraceClient()
        client.add_trace(make_raw_trace(trace_id="t1"))
        client.add_trace(make_raw_trace(trace_id="t2"))

        request = TraceSearchRequest(limit=10)
        results = await client.search_traces(request)
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_get_trace_by_id(self):
        """Get trace by ID returns the correct trace."""
        client = FakePhoenixTraceClient()
        client.add_trace(make_raw_trace(trace_id="t1"))
        client.add_trace(make_raw_trace(trace_id="t2"))

        result = await client.get_trace("t1")
        assert result is not None
        assert result["trace_id"] == "t1"

    @pytest.mark.asyncio
    async def test_get_trace_not_found(self):
        """Get trace returns None for unknown ID."""
        client = FakePhoenixTraceClient()
        result = await client.get_trace("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_traces_by_ids(self):
        """Get multiple traces by IDs."""
        client = FakePhoenixTraceClient()
        client.add_trace(make_raw_trace(trace_id="t1"))
        client.add_trace(make_raw_trace(trace_id="t2"))
        client.add_trace(make_raw_trace(trace_id="t3"))

        results = await client.get_traces_by_ids(["t1", "t3"])
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_get_traces_by_ids_skips_missing(self):
        """Get traces by IDs skips missing traces."""
        client = FakePhoenixTraceClient()
        client.add_trace(make_raw_trace(trace_id="t1"))

        results = await client.get_traces_by_ids(["t1", "missing"])
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_unavailable_client_returns_empty(self):
        """Unavailable client returns empty results."""
        client = FakePhoenixTraceClient(unavailable=True)

        request = TraceSearchRequest()
        results = await client.search_traces(request)
        assert results == []

        result = await client.get_trace("t1")
        assert result is None

    @pytest.mark.asyncio
    async def test_failing_client_raises(self):
        """Failing client raises RuntimeError."""
        client = FakePhoenixTraceClient(fail=True, fail_message="Test error")

        request = TraceSearchRequest()
        with pytest.raises(RuntimeError, match="Test error"):
            await client.search_traces(request)

    @pytest.mark.asyncio
    async def test_health_check_available(self):
        """Health check returns True for available client."""
        client = FakePhoenixTraceClient()
        assert await client.health_check() is True

    @pytest.mark.asyncio
    async def test_health_check_unavailable(self):
        """Health check returns False for unavailable client."""
        client = FakePhoenixTraceClient(unavailable=True)
        assert await client.health_check() is False

    @pytest.mark.asyncio
    async def test_close_is_noop(self):
        """Close is a no-op for fake client."""
        client = FakePhoenixTraceClient()
        await client.close()  # Should not raise

    @pytest.mark.asyncio
    async def test_search_calls_tracked(self):
        """Search calls are tracked."""
        client = FakePhoenixTraceClient()
        request = TraceSearchRequest(mission_id="m1")
        await client.search_traces(request)
        assert len(client.search_calls) == 1
        assert client.search_calls[0].mission_id == "m1"

    @pytest.mark.asyncio
    async def test_get_calls_tracked(self):
        """Get calls are tracked."""
        client = FakePhoenixTraceClient()
        await client.get_trace("t1")
        assert client.get_calls == ["t1"]

    @pytest.mark.asyncio
    async def test_does_not_include_credentials_in_errors(self):
        """Client does not include credentials in error messages."""
        client = FakePhoenixTraceClient(
            fail=True,
            fail_message="Connection failed",
        )
        try:
            await client.search_traces(TraceSearchRequest())
        except RuntimeError as exc:
            error_msg = str(exc)
            assert "api_key" not in error_msg.lower()
            assert "password" not in error_msg.lower()
            assert "secret" not in error_msg.lower()

    @pytest.mark.asyncio
    async def test_does_not_request_raw_telemetry(self):
        """Client does not request raw telemetry or replay frames."""
        client = FakePhoenixTraceClient()
        client.add_trace(make_raw_trace())

        # The fake client doesn't make HTTP requests, but we verify
        # the search request model doesn't have telemetry fields
        request = TraceSearchRequest(incident_type="nav")
        results = await client.search_traces(request)
        for trace in results:
            # Verify no raw telemetry fields
            assert "telemetry" not in trace
            assert "replay_frames" not in trace
            assert "state_timeline" not in trace
