"""
Phase 2 Mission Client
======================
Async HTTP client for consuming Phase 2 mission data.

Fetches bounded mission detail for graph projection.
Validates required fields before returning.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import httpx

from .config import settings

logger = logging.getLogger("phase7.phase2_client")

# Required fields for a valid Phase 2 mission detail contract.
_REQUIRED_MISSION_FIELDS = [
    "mission_id",
    "drone_id",
    "start_time",
    "mission_result",
]


class Phase2ClientError(Exception):
    """Base error for Phase 2 client failures."""
    pass


class Phase2NotFoundError(Phase2ClientError):
    """Mission not found in Phase 2."""
    pass


class Phase2UnavailableError(Phase2ClientError):
    """Phase 2 API is unreachable or returned a server error."""
    pass


class Phase2Client:
    """
    HTTP client for the Phase 2 Mission Replay API.

    Fetches bounded mission detail for graph projection.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> None:
        self._base_url = (base_url or settings.PHASE2_API_URL).rstrip("/")
        self._timeout = timeout or settings.MEMORY_CLIENT_TIMEOUT

    async def get_mission(self, mission_id: str) -> dict[str, Any]:
        """
        Fetch mission detail from Phase 2.

        Args:
            mission_id: Mission identifier.

        Returns:
            Bounded mission detail dict.

        Raises:
            Phase2NotFoundError: If the mission does not exist.
            Phase2UnavailableError: If Phase 2 is unreachable.
            ValueError: If the response is missing required fields.
        """
        url = f"{self._base_url}/api/v1/missions/{mission_id}"

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.get(url)
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            raise Phase2UnavailableError(
                f"Phase 2 API unreachable at {self._base_url}: {exc}"
            ) from exc
        except httpx.TimeoutException as exc:
            raise Phase2UnavailableError(
                f"Phase 2 API timeout: {exc}"
            ) from exc

        if response.status_code == 404:
            raise Phase2NotFoundError(
                f"Mission '{mission_id}' not found in Phase 2"
            )

        if response.status_code >= 500:
            raise Phase2UnavailableError(
                f"Phase 2 API server error: {response.status_code}"
            )

        if response.status_code >= 400:
            raise Phase2ClientError(
                f"Phase 2 API client error: {response.status_code}"
            )

        data = response.json()

        # Validate required fields
        missing = [f for f in _REQUIRED_MISSION_FIELDS if f not in data or data[f] is None]
        if missing:
            raise ValueError(
                f"Phase 2 mission response missing required fields: "
                f"{', '.join(missing)}"
            )

        # Validate mission_id matches
        if data.get("mission_id") != mission_id:
            raise ValueError(
                f"Mission ID mismatch: requested '{mission_id}', "
                f"got '{data.get('mission_id')}'"
            )

        return data

    async def health_check(self) -> bool:
        """Check if Phase 2 API is reachable."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self._base_url}/health")
                return response.status_code == 200
        except Exception:
            return False
