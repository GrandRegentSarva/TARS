"""
Replay Client
=============
HTTP client for fetching replay frames from the Phase 2 API.

Phase 3 treats Phase 2 as the source of replay truth and does not
read PostgreSQL directly. All replay data flows through the Phase 2
REST API.
"""

from __future__ import annotations

import logging
from typing import Optional

import httpx

from .config import settings
from .models import ReplayData

logger = logging.getLogger("phase3.replay_client")


class ReplayClient:
    """
    Async HTTP client for the Phase 2 Replay API.

    Fetches ordered replay frames for a given mission.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> None:
        self._base_url = (base_url or settings.PHASE2_API_URL).rstrip("/")
        self._timeout = timeout or settings.REPLAY_CLIENT_TIMEOUT

    async def fetch_replay(
        self,
        mission_id: str,
        from_ms: int = 0,
        to_ms: Optional[int] = None,
        speed: float = 1.0,
    ) -> ReplayData:
        """
        Fetch replay frames from Phase 2.

        Args:
            mission_id: The mission to replay.
            from_ms: Start elapsed_ms (inclusive).
            to_ms: End elapsed_ms (inclusive). None = end of mission.
            speed: Playback speed multiplier (metadata only).

        Returns:
            ReplayData containing ordered frames.

        Raises:
            httpx.HTTPStatusError: If Phase 2 returns a non-2xx status.
            httpx.ConnectError: If Phase 2 API is unreachable.
        """
        url = f"{self._base_url}/api/v1/missions/{mission_id}/replay"

        params: dict[str, str | int | float] = {
            "from_ms": from_ms,
            "speed": speed,
        }
        if to_ms is not None:
            params["to_ms"] = to_ms

        logger.info(
            "Fetching replay for mission %s (from_ms=%d, to_ms=%s)",
            mission_id,
            from_ms,
            to_ms,
        )

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()

        data = response.json()
        replay = ReplayData.model_validate(data)

        logger.info(
            "Received %d frames for mission %s",
            replay.total_frames,
            mission_id,
        )

        return replay
