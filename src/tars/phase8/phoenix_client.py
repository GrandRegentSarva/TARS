"""
Phoenix Trace Client
====================
Queries Phoenix for trace metadata and bounded spans using the
Phoenix REST API.

Design principles:
- Fail-open: Phoenix unavailability returns empty results, never crashes.
- Bounded queries: All queries use TARS trace attributes from Phase 6.
- No arbitrary queries: Only structured attribute-based search is supported.
- No mutations: Read-only access to Phoenix trace data.
- No credentials in responses: Errors are sanitized before return.
- Short timeouts: Introspection is advisory context only.

The client queries Phoenix's REST API for spans/traces that have
TARS-specific attributes set by Phase 6 instrumentation.
"""

from __future__ import annotations

import logging
from typing import Any, Optional, Protocol, runtime_checkable

import httpx

from .config import PhoenixMCPSettings, mcp_settings
from .models import TraceSearchRequest

logger = logging.getLogger("phase8.phoenix_client")

# Phase 6 attribute names used for filtering
_ATTR_MAP = {
    "mission_id": "tars.mission.id",
    "incident_id": "tars.incident.id",
    "incident_type": "tars.incident.type",
    "root_cause": "tars.reasoning.root_cause",
    "prompt_version": "tars.reasoning.prompt_version",
    "model": "llm.model_name",
    "outcome": "tars.reasoning.outcome",
    "reasoning_id": "tars.reasoning.id",
}


@runtime_checkable
class PhoenixTraceClientProtocol(Protocol):
    """Protocol for Phoenix trace clients (production and fake)."""

    async def search_traces(
        self,
        request: TraceSearchRequest,
    ) -> list[dict[str, Any]]:
        """Search for traces matching the given filters."""
        ...

    async def get_trace(
        self,
        trace_id: str,
    ) -> Optional[dict[str, Any]]:
        """Get a single trace by ID with its spans."""
        ...

    async def get_traces_by_ids(
        self,
        trace_ids: list[str],
    ) -> list[dict[str, Any]]:
        """Get multiple traces by their IDs."""
        ...

    async def health_check(self) -> bool:
        """Check if Phoenix is reachable."""
        ...

    async def close(self) -> None:
        """Close any open connections."""
        ...


class PhoenixTraceClient:
    """
    Production Phoenix trace client using the Phoenix REST/GraphQL API.

    Queries Phoenix for traces with TARS-specific attributes set by
    Phase 6 instrumentation. All queries are bounded and read-only.
    """

    def __init__(
        self,
        settings: Optional[PhoenixMCPSettings] = None,
    ) -> None:
        self._settings = settings or mcp_settings
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create the HTTP client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self._settings.traces_api_url,
                timeout=httpx.Timeout(self._settings.TIMEOUT_SECONDS),
            )
        return self._client

    async def search_traces(
        self,
        request: TraceSearchRequest,
    ) -> list[dict[str, Any]]:
        """
        Search Phoenix for traces matching TARS operational attributes.

        Builds a bounded query from the request filters and returns
        raw trace data for summarization.

        Args:
            request: Bounded search request with TARS filters.

        Returns:
            List of raw trace dicts from Phoenix.
            Empty list on any failure.
        """
        try:
            client = await self._get_client()

            # Build the GraphQL query for Phoenix
            # Phoenix uses GraphQL for trace queries
            query = self._build_search_query(request)

            response = await client.post(
                "/graphql",
                json={"query": query},
            )

            if response.status_code == 404:
                logger.debug("Phoenix GraphQL endpoint not found")
                return []

            if response.status_code >= 500:
                logger.warning(
                    "Phoenix server error: %d", response.status_code
                )
                return []

            response.raise_for_status()

            data = response.json()
            return self._parse_search_response(data, request.limit)

        except httpx.TimeoutException:
            logger.warning("Phoenix trace search timed out")
            return []
        except httpx.ConnectError:
            logger.warning("Phoenix is unreachable")
            return []
        except Exception as exc:
            # Sanitize error message before logging
            safe_msg = str(exc)
            for pattern in ["api_key", "password", "secret", "token"]:
                if pattern in safe_msg.lower():
                    safe_msg = "Phoenix query failed (details redacted)"
                    break
            logger.warning("Phoenix trace search failed: %s", safe_msg)
            return []

    async def get_trace(
        self,
        trace_id: str,
    ) -> Optional[dict[str, Any]]:
        """
        Get a single trace by ID with its spans.

        Args:
            trace_id: Phoenix trace identifier.

        Returns:
            Raw trace dict with spans, or None on failure.
        """
        try:
            client = await self._get_client()

            query = self._build_trace_query(trace_id)

            response = await client.post(
                "/graphql",
                json={"query": query},
            )

            if response.status_code == 404:
                logger.debug("Trace '%s' not found", trace_id)
                return None

            if response.status_code >= 500:
                logger.warning(
                    "Phoenix server error getting trace '%s': %d",
                    trace_id,
                    response.status_code,
                )
                return None

            response.raise_for_status()

            data = response.json()
            return self._parse_trace_response(data, trace_id)

        except httpx.TimeoutException:
            logger.warning("Phoenix get_trace timed out for '%s'", trace_id)
            return None
        except httpx.ConnectError:
            logger.warning("Phoenix is unreachable")
            return None
        except Exception as exc:
            safe_msg = str(exc)
            for pattern in ["api_key", "password", "secret", "token"]:
                if pattern in safe_msg.lower():
                    safe_msg = "Phoenix query failed (details redacted)"
                    break
            logger.warning(
                "Phoenix get_trace failed for '%s': %s", trace_id, safe_msg
            )
            return None

    async def get_traces_by_ids(
        self,
        trace_ids: list[str],
    ) -> list[dict[str, Any]]:
        """
        Get multiple traces by their IDs.

        Args:
            trace_ids: List of Phoenix trace identifiers.

        Returns:
            List of raw trace dicts. Missing traces are omitted.
        """
        results: list[dict[str, Any]] = []
        for trace_id in trace_ids[:self._settings.MAX_TRACE_IDS]:
            trace = await self.get_trace(trace_id)
            if trace is not None:
                results.append(trace)
        return results

    async def health_check(self) -> bool:
        """
        Check if Phoenix is reachable.

        Returns:
            True if Phoenix responds, False otherwise.
        """
        try:
            client = await self._get_client()
            response = await client.get("/")
            return response.status_code < 500
        except Exception:
            return False

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    # -----------------------------------------------------------------------
    # Query Builders
    # -----------------------------------------------------------------------

    def _build_search_query(self, request: TraceSearchRequest) -> str:
        """
        Build a Phoenix GraphQL query for trace search.

        Uses TARS-specific span attributes for filtering.
        """
        # Build filter conditions
        conditions: list[str] = []

        if request.mission_id:
            conditions.append(
                f'{{ attribute: {{ name: "{_ATTR_MAP["mission_id"]}", '
                f'value: {{ stringValue: "{request.mission_id}" }} }} }}'
            )
        if request.incident_id:
            conditions.append(
                f'{{ attribute: {{ name: "{_ATTR_MAP["incident_id"]}", '
                f'value: {{ stringValue: "{request.incident_id}" }} }} }}'
            )
        if request.incident_type:
            conditions.append(
                f'{{ attribute: {{ name: "{_ATTR_MAP["incident_type"]}", '
                f'value: {{ stringValue: "{request.incident_type}" }} }} }}'
            )
        if request.root_cause:
            conditions.append(
                f'{{ attribute: {{ name: "{_ATTR_MAP["root_cause"]}", '
                f'value: {{ stringValue: "{request.root_cause}" }} }} }}'
            )
        if request.prompt_version:
            conditions.append(
                f'{{ attribute: {{ name: "{_ATTR_MAP["prompt_version"]}", '
                f'value: {{ stringValue: "{request.prompt_version}" }} }} }}'
            )
        if request.model:
            conditions.append(
                f'{{ attribute: {{ name: "{_ATTR_MAP["model"]}", '
                f'value: {{ stringValue: "{request.model}" }} }} }}'
            )
        if request.outcome:
            conditions.append(
                f'{{ attribute: {{ name: "{_ATTR_MAP["outcome"]}", '
                f'value: {{ stringValue: "{request.outcome}" }} }} }}'
            )

        # Time range filter
        time_range = ""
        if request.from_time or request.to_time:
            parts = []
            if request.from_time:
                parts.append(f'startTime: "{request.from_time}"')
            if request.to_time:
                parts.append(f'endTime: "{request.to_time}"')
            time_range = f"timeRange: {{ {', '.join(parts)} }}"

        # Build the query
        filter_str = ""
        if conditions:
            filter_str = f"filterConditions: [{', '.join(conditions)}]"

        limit = min(request.limit, self._settings.MAX_LIMIT)

        query = f"""
        query {{
            spans(
                first: {limit}
                {filter_str}
                {time_range}
                sort: {{ col: startTime, dir: desc }}
            ) {{
                edges {{
                    node {{
                        context {{
                            traceId
                            spanId
                        }}
                        name
                        statusCode
                        statusMessage
                        startTime
                        endTime
                        latencyMs
                        spanKind
                        attributes
                    }}
                }}
            }}
        }}
        """
        return query

    def _build_trace_query(self, trace_id: str) -> str:
        """Build a Phoenix GraphQL query for a single trace."""
        return f"""
        query {{
            spans(
                first: 50
                filterConditions: [{{
                    attribute: {{ name: "context.trace_id", value: {{ stringValue: "{trace_id}" }} }}
                }}]
                sort: {{ col: startTime, dir: asc }}
            ) {{
                edges {{
                    node {{
                        context {{
                            traceId
                            spanId
                        }}
                        name
                        statusCode
                        statusMessage
                        startTime
                        endTime
                        latencyMs
                        spanKind
                        attributes
                    }}
                }}
            }}
        }}
        """

    # -----------------------------------------------------------------------
    # Response Parsers
    # -----------------------------------------------------------------------

    def _parse_search_response(
        self,
        data: dict[str, Any],
        limit: int,
    ) -> list[dict[str, Any]]:
        """Parse Phoenix GraphQL search response into trace dicts."""
        try:
            edges = (
                data.get("data", {})
                .get("spans", {})
                .get("edges", [])
            )

            # Group spans by trace ID
            traces_by_id: dict[str, dict[str, Any]] = {}
            for edge in edges:
                node = edge.get("node", {})
                if not node:
                    continue

                context = node.get("context", {})
                trace_id = context.get("traceId", "")
                if not trace_id:
                    continue

                if trace_id not in traces_by_id:
                    traces_by_id[trace_id] = {
                        "trace_id": trace_id,
                        "spans": [],
                        "attributes": {},
                    }

                # Parse attributes safely
                raw_attrs = node.get("attributes", {})
                if isinstance(raw_attrs, str):
                    import json
                    try:
                        raw_attrs = json.loads(raw_attrs)
                    except (json.JSONDecodeError, TypeError):
                        raw_attrs = {}

                span_data = {
                    "name": node.get("name", "unknown"),
                    "status": {
                        "status_code": node.get("statusCode", "UNSET"),
                        "description": node.get("statusMessage", ""),
                    },
                    "duration_ms": node.get("latencyMs"),
                    "start_time": node.get("startTime"),
                    "end_time": node.get("endTime"),
                    "attributes": raw_attrs,
                }

                traces_by_id[trace_id]["spans"].append(span_data)

                # Merge attributes to trace level
                for k, v in raw_attrs.items():
                    if k not in traces_by_id[trace_id]["attributes"]:
                        traces_by_id[trace_id]["attributes"][k] = v

                # Set trace-level timing from root span
                if not traces_by_id[trace_id].get("created_at"):
                    traces_by_id[trace_id]["created_at"] = node.get("startTime")

                # Set trace-level duration
                if node.get("latencyMs") is not None:
                    existing = traces_by_id[trace_id].get("duration_ms")
                    new_val = node.get("latencyMs")
                    if existing is None or (new_val is not None and new_val > existing):
                        traces_by_id[trace_id]["duration_ms"] = new_val

            return list(traces_by_id.values())[:limit]

        except Exception as exc:
            logger.warning("Failed to parse Phoenix search response: %s", exc)
            return []

    def _parse_trace_response(
        self,
        data: dict[str, Any],
        trace_id: str,
    ) -> Optional[dict[str, Any]]:
        """Parse Phoenix GraphQL response for a single trace."""
        try:
            edges = (
                data.get("data", {})
                .get("spans", {})
                .get("edges", [])
            )

            if not edges:
                return None

            result: dict[str, Any] = {
                "trace_id": trace_id,
                "spans": [],
                "attributes": {},
            }

            for edge in edges:
                node = edge.get("node", {})
                if not node:
                    continue

                raw_attrs = node.get("attributes", {})
                if isinstance(raw_attrs, str):
                    import json
                    try:
                        raw_attrs = json.loads(raw_attrs)
                    except (json.JSONDecodeError, TypeError):
                        raw_attrs = {}

                span_data = {
                    "name": node.get("name", "unknown"),
                    "status": {
                        "status_code": node.get("statusCode", "UNSET"),
                        "description": node.get("statusMessage", ""),
                    },
                    "duration_ms": node.get("latencyMs"),
                    "start_time": node.get("startTime"),
                    "end_time": node.get("endTime"),
                    "attributes": raw_attrs,
                }

                result["spans"].append(span_data)

                # Merge attributes
                for k, v in raw_attrs.items():
                    if k not in result["attributes"]:
                        result["attributes"][k] = v

            if not result.get("created_at") and result["spans"]:
                result["created_at"] = result["spans"][0].get("start_time")

            if result["spans"]:
                durations = [
                    s.get("duration_ms")
                    for s in result["spans"]
                    if s.get("duration_ms") is not None
                ]
                if durations:
                    result["duration_ms"] = max(durations)

            return result

        except Exception as exc:
            logger.warning(
                "Failed to parse Phoenix trace response for '%s': %s",
                trace_id,
                exc,
            )
            return None


class FakePhoenixTraceClient:
    """
    Deterministic fake Phoenix client for testing.

    Returns predictable trace data without requiring a live Phoenix
    instance. Supports configurable responses and failure simulation.
    """

    def __init__(
        self,
        *,
        traces: Optional[list[dict[str, Any]]] = None,
        fail: bool = False,
        fail_message: str = "Fake Phoenix failure",
        unavailable: bool = False,
    ) -> None:
        self._traces = traces or []
        self._fail = fail
        self._fail_message = fail_message
        self._unavailable = unavailable
        self._search_calls: list[TraceSearchRequest] = []
        self._get_calls: list[str] = []

    @property
    def search_calls(self) -> list[TraceSearchRequest]:
        """Return the list of search requests received."""
        return self._search_calls

    @property
    def get_calls(self) -> list[str]:
        """Return the list of trace IDs requested."""
        return self._get_calls

    def add_trace(self, trace: dict[str, Any]) -> None:
        """Add a trace to the fake store."""
        self._traces.append(trace)

    async def search_traces(
        self,
        request: TraceSearchRequest,
    ) -> list[dict[str, Any]]:
        """Return matching traces from the fake store."""
        self._search_calls.append(request)

        if self._fail:
            raise RuntimeError(self._fail_message)
        if self._unavailable:
            return []

        # Simple attribute matching
        results: list[dict[str, Any]] = []
        for trace in self._traces:
            attrs = trace.get("attributes", {})
            if self._matches(request, attrs):
                results.append(trace)

        return results[: request.limit]

    async def get_trace(
        self,
        trace_id: str,
    ) -> Optional[dict[str, Any]]:
        """Return a trace by ID from the fake store."""
        self._get_calls.append(trace_id)

        if self._fail:
            raise RuntimeError(self._fail_message)
        if self._unavailable:
            return None

        for trace in self._traces:
            if trace.get("trace_id") == trace_id:
                return trace
        return None

    async def get_traces_by_ids(
        self,
        trace_ids: list[str],
    ) -> list[dict[str, Any]]:
        """Return traces by IDs from the fake store."""
        results: list[dict[str, Any]] = []
        for trace_id in trace_ids:
            trace = await self.get_trace(trace_id)
            if trace is not None:
                results.append(trace)
        return results

    async def health_check(self) -> bool:
        """Return True unless configured as unavailable."""
        return not self._unavailable and not self._fail

    async def close(self) -> None:
        """No-op for fake client."""
        pass

    @staticmethod
    def _matches(
        request: TraceSearchRequest,
        attrs: dict[str, Any],
    ) -> bool:
        """Check if trace attributes match the search request."""
        checks = [
            ("mission_id", request.mission_id, _ATTR_MAP.get("mission_id")),
            ("incident_id", request.incident_id, _ATTR_MAP.get("incident_id")),
            ("incident_type", request.incident_type, _ATTR_MAP.get("incident_type")),
            ("root_cause", request.root_cause, _ATTR_MAP.get("root_cause")),
            ("prompt_version", request.prompt_version, _ATTR_MAP.get("prompt_version")),
            ("model", request.model, _ATTR_MAP.get("model")),
            ("outcome", request.outcome, _ATTR_MAP.get("outcome")),
        ]

        for field_name, filter_value, attr_key in checks:
            if filter_value is not None and attr_key is not None:
                trace_value = attrs.get(attr_key)
                if trace_value != filter_value:
                    return False

        return True
