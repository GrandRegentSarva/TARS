"""
Phoenix Trace Metadata Client
================================
Read-only HTTP client for fetching safe Phoenix trace metadata.

Only trace IDs and execution metadata are fetched. Trace bodies,
prompts, responses, and credentials are never copied.

Phoenix is optional. Its unavailability produces warnings, not crashes.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import httpx

from ..config import settings

logger = logging.getLogger("phase10.adapters.phoenix")


class PhoenixClientError(Exception):
    """Error communicating with Phoenix API."""


class PhoenixClient:
    """
    Async HTTP client for Phoenix trace metadata.

    Reads only trace IDs and safe execution attributes.
    Never copies trace bodies, prompts, responses, or credentials.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> None:
        self._base_url = (base_url or settings.PHOENIX_BASE_URL).rstrip("/")
        self._timeout = timeout or settings.LEARNING_CLIENT_TIMEOUT
        self._enabled = settings.LEARNING_TRACE_METADATA_ENABLED

    @property
    def is_enabled(self) -> bool:
        """Whether trace metadata collection is enabled."""
        return self._enabled

    async def get_trace_metadata(
        self,
        trace_id: str,
    ) -> Optional[dict[str, Any]]:
        """
        Get safe metadata for a trace.

        Returns only trace ID, status, duration, model, and prompt version.
        Never returns trace body, prompts, or responses.
        """
        if not self._enabled:
            return None

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.get(
                    f"{self._base_url}/api/v1/traces/{trace_id}"
                )
                if resp.status_code == 404:
                    return None
                resp.raise_for_status()
                full_trace = resp.json()

                # Extract only safe metadata fields
                return self._extract_safe_metadata(trace_id, full_trace)
        except httpx.ConnectError as exc:
            logger.warning("Phoenix API unreachable: %s", exc)
            return None
        except Exception as exc:
            logger.warning("Phoenix API error: %s", exc)
            return None

    async def get_trace_ids_for_mission(
        self,
        mission_id: str,
        limit: int = 50,
    ) -> list[str]:
        """
        Get trace IDs associated with a mission.

        Returns only trace IDs, not trace bodies.
        """
        if not self._enabled:
            return []

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.get(
                    f"{self._base_url}/api/v1/traces",
                    params={
                        "mission_id": mission_id,
                        "limit": limit,
                    },
                )
                if resp.status_code == 404:
                    return []
                resp.raise_for_status()
                data = resp.json()
                traces = data.get("traces", data) if isinstance(data, dict) else data
                if isinstance(traces, list):
                    return [
                        t.get("trace_id", t.get("id", ""))
                        for t in traces
                        if isinstance(t, dict)
                    ][:limit]
                return []
        except httpx.ConnectError as exc:
            logger.warning("Phoenix API unreachable: %s", exc)
            return []
        except Exception as exc:
            logger.warning("Phoenix API error: %s", exc)
            return []

    async def health_check(self) -> bool:
        """Check Phoenix API connectivity."""
        if not self._enabled:
            return False
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                resp = await client.get(f"{self._base_url}/health")
                return resp.status_code < 500
        except Exception:
            return False

    def _extract_safe_metadata(
        self,
        trace_id: str,
        full_trace: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Extract only safe metadata from a full trace response.

        Safe fields: trace_id, status, duration_ms, model, prompt_version,
        span_count, error_count, start_time, end_time.

        Excluded: prompts, responses, inputs, outputs, embeddings,
        credentials, tokens.
        """
        safe = {
            "trace_id": trace_id,
            "status": full_trace.get("status"),
            "duration_ms": full_trace.get("duration_ms"),
            "model": full_trace.get("model"),
            "prompt_version": full_trace.get("prompt_version"),
            "span_count": full_trace.get("span_count"),
            "error_count": full_trace.get("error_count"),
            "start_time": full_trace.get("start_time"),
            "end_time": full_trace.get("end_time"),
        }
        # Remove None values
        return {k: v for k, v in safe.items() if v is not None}
