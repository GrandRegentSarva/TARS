"""
Phase 4 Incident Client
========================
Async HTTP client for consuming Phase 4 incident data.

Fetches incident lists for a mission for graph projection.
Validates required fields and cross-phase identifiers.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import httpx

from .config import settings

logger = logging.getLogger("phase7.phase4_client")

# Required fields for a valid Phase 4 incident contract.
_REQUIRED_INCIDENT_FIELDS = [
    "incident_id",
    "mission_id",
    "incident_type",
    "severity",
    "start_ms",
    "end_ms",
]


class Phase4ClientError(Exception):
    """Base error for Phase 4 client failures."""
    pass


class Phase4UnavailableError(Phase4ClientError):
    """Phase 4 API is unreachable or returned a server error."""
    pass


class Phase4Client:
    """
    HTTP client for the Phase 4 Incident Engine API.

    Fetches incident lists for graph projection.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> None:
        self._base_url = (base_url or settings.PHASE4_API_URL).rstrip("/")
        self._timeout = timeout or settings.MEMORY_CLIENT_TIMEOUT

    async def get_incidents(self, mission_id: str) -> list[dict[str, Any]]:
        """
        Fetch all incidents for a mission from Phase 4.

        Args:
            mission_id: Mission identifier.

        Returns:
            List of incident dicts.

        Raises:
            Phase4UnavailableError: If Phase 4 is unreachable.
            ValueError: If any incident is missing required fields or
                       has a mission_id mismatch.
        """
        url = f"{self._base_url}/api/v1/incidents/{mission_id}"

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.get(url)
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            raise Phase4UnavailableError(
                f"Phase 4 API unreachable at {self._base_url}: {exc}"
            ) from exc
        except httpx.TimeoutException as exc:
            raise Phase4UnavailableError(
                f"Phase 4 API timeout: {exc}"
            ) from exc

        if response.status_code >= 500:
            raise Phase4UnavailableError(
                f"Phase 4 API server error: {response.status_code}"
            )

        if response.status_code >= 400:
            raise Phase4ClientError(
                f"Phase 4 API client error: {response.status_code}"
            )

        data = response.json()
        incidents = data.get("incidents", [])

        # Validate each incident
        validated = []
        for inc in incidents:
            self._validate_incident(inc, mission_id)
            validated.append(inc)

        logger.info(
            "Fetched %d incidents for mission '%s' from Phase 4",
            len(validated),
            mission_id,
        )
        return validated

    def _validate_incident(
        self,
        incident: dict[str, Any],
        expected_mission_id: str,
    ) -> None:
        """
        Validate a single incident dict.

        Raises:
            ValueError: If required fields are missing or identifiers mismatch.
        """
        missing = [
            f for f in _REQUIRED_INCIDENT_FIELDS
            if f not in incident or incident[f] is None
        ]
        if missing:
            raise ValueError(
                f"Phase 4 incident missing required fields: "
                f"{', '.join(missing)}"
            )

        if incident.get("mission_id") != expected_mission_id:
            raise ValueError(
                f"Incident mission_id mismatch: expected '{expected_mission_id}', "
                f"got '{incident.get('mission_id')}'"
            )

    async def health_check(self) -> bool:
        """Check if Phase 4 API is reachable."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self._base_url}/health")
                return response.status_code == 200
        except Exception:
            return False
