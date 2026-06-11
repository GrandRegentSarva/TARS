"""
Phase 3 State Client
====================
Async HTTP client for consuming Phase 3 state timelines.

Fetches state snapshots from the Phase 3 State Engine API
for incident detection processing.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import httpx

from .config import settings

logger = logging.getLogger("phase4.state_client")


class StateClient:
    """
    HTTP client for the Phase 3 State Engine API.

    Fetches state timelines for incident detection.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> None:
        self._base_url = (base_url or settings.PHASE3_API_URL).rstrip("/")
        self._timeout = timeout or settings.STATE_CLIENT_TIMEOUT

    async def get_timeline(
        self,
        mission_id: str,
        from_ms: int = 0,
        to_ms: Optional[int] = None,
        limit: int = 10000,
    ) -> dict[str, Any]:
        """
        Fetch state timeline from Phase 3 API.

        Args:
            mission_id: Mission identifier.
            from_ms: Start elapsed_ms (inclusive).
            to_ms: End elapsed_ms (inclusive). None = all.
            limit: Maximum states to return.

        Returns:
            Timeline response dict with 'states', 'total', etc.

        Raises:
            httpx.HTTPStatusError: On non-2xx response.
            httpx.ConnectError: If Phase 3 API is unreachable.
        """
        url = f"{self._base_url}/api/v1/state/{mission_id}/timeline"
        params: dict[str, Any] = {"from_ms": from_ms, "limit": limit}
        if to_ms is not None:
            params["to_ms"] = to_ms

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            return response.json()

    async def health_check(self) -> bool:
        """Check if Phase 3 API is reachable."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self._base_url}/health")
                return response.status_code == 200
        except Exception:
            return False
