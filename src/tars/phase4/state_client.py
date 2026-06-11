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
        page_size: int = 10000,
    ) -> dict[str, Any]:
        """
        Fetch the complete state timeline from Phase 3 API.

        Automatically paginates when the mission has more states than
        *page_size* so that large missions are never silently truncated.

        Args:
            mission_id: Mission identifier.
            from_ms: Start elapsed_ms (inclusive).
            to_ms: End elapsed_ms (inclusive). None = all.
            page_size: States per request page.

        Returns:
            Timeline response dict with 'states', 'total', etc.

        Raises:
            httpx.HTTPStatusError: On non-2xx response.
            httpx.ConnectError: If Phase 3 API is unreachable.
        """
        url = f"{self._base_url}/api/v1/state/{mission_id}/timeline"
        all_states: list[dict[str, Any]] = []
        cursor_from_ms = from_ms
        total_reported: int | None = None

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            while True:
                params: dict[str, Any] = {
                    "from_ms": cursor_from_ms,
                    "limit": page_size,
                }
                if to_ms is not None:
                    params["to_ms"] = to_ms

                response = await client.get(url, params=params)
                response.raise_for_status()
                data = response.json()

                page_states = data.get("states", [])
                if total_reported is None:
                    total_reported = data.get("total", len(page_states))

                if not page_states:
                    break

                all_states.extend(page_states)

                # If we got fewer than page_size, we've reached the end
                if len(page_states) < page_size:
                    break

                # Advance cursor past the last state we received
                last_ms = page_states[-1].get("elapsed_ms", cursor_from_ms)
                next_from = last_ms + 1
                if next_from <= cursor_from_ms:
                    # Safety: avoid infinite loop if elapsed_ms doesn't advance
                    logger.warning(
                        "Pagination stalled at from_ms=%d for mission '%s'",
                        cursor_from_ms, mission_id,
                    )
                    break
                cursor_from_ms = next_from

        return {
            "mission_id": mission_id,
            "states": all_states,
            "total": total_reported or len(all_states),
            "from_ms": from_ms,
            "to_ms": to_ms,
        }

    async def health_check(self) -> bool:
        """Check if Phase 3 API is reachable."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self._base_url}/health")
                return response.status_code == 200
        except Exception:
            return False
