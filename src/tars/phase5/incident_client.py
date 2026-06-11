"""
Phase 4 Incident Client
========================
Async HTTP client for consuming Phase 4 incident data.

Fetches individual incidents from the Phase 4 Incident Engine API
for reasoning analysis. Validates both identifiers and required
incident contract fields before returning.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import httpx

from .config import settings

logger = logging.getLogger("phase5.incident_client")

# Required fields for a valid Phase 4 incident contract.
# A response missing any of these is rejected before reasoning.
_REQUIRED_INCIDENT_FIELDS = [
    "incident_type",
    "severity",
    "start_ms",
    "end_ms",
    "contributing_states",
    "peak_risk",
    "phases",
    "evidence",
]


def _validate_incident_fields(data: dict[str, Any]) -> None:
    """
    Validate that a Phase 4 response contains all required incident fields.

    Raises:
        ValueError: If any required field is missing or has an invalid type.
    """
    missing = [
        field for field in _REQUIRED_INCIDENT_FIELDS
        if field not in data
    ]
    if missing:
        raise ValueError(
            f"Phase 4 incident response missing required fields: "
            f"{', '.join(missing)}"
        )

    # Validate field types for critical fields
    if not isinstance(data.get("incident_type"), str) or not data["incident_type"]:
        raise ValueError(
            "Phase 4 incident has empty or invalid 'incident_type'"
        )

    if not isinstance(data.get("severity"), str) or not data["severity"]:
        raise ValueError(
            "Phase 4 incident has empty or invalid 'severity'"
        )

    if not isinstance(data.get("evidence"), list):
        raise ValueError(
            "Phase 4 incident 'evidence' must be a list"
        )

    if not isinstance(data.get("phases"), list):
        raise ValueError(
            "Phase 4 incident 'phases' must be a list"
        )


class IncidentClient:
    """
    HTTP client for the Phase 4 Incident Engine API.

    Fetches individual incidents for reasoning analysis.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> None:
        self._base_url = (base_url or settings.PHASE4_API_URL).rstrip("/")
        self._timeout = timeout or settings.INCIDENT_CLIENT_TIMEOUT

    async def get_incident(
        self,
        mission_id: str,
        incident_id: str,
    ) -> dict[str, Any]:
        """
        Fetch a single incident from the Phase 4 API.

        Args:
            mission_id: Mission identifier.
            incident_id: Incident identifier.

        Returns:
            Incident dict from Phase 4.

        Raises:
            httpx.HTTPStatusError: On non-2xx response (404, 5xx, etc.).
            httpx.ConnectError: If Phase 4 API is unreachable.
            ValueError: On identifier mismatch or missing required fields.
        """
        url = f"{self._base_url}/api/v1/incidents/{mission_id}/{incident_id}"

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.get(url)
            response.raise_for_status()
            data = response.json()

        # Validate that the returned incident matches the requested IDs
        returned_mission = data.get("mission_id")
        returned_incident = data.get("incident_id")

        if returned_mission != mission_id:
            raise ValueError(
                f"Mission ID mismatch: requested '{mission_id}', "
                f"got '{returned_mission}'"
            )

        if returned_incident != incident_id:
            raise ValueError(
                f"Incident ID mismatch: requested '{incident_id}', "
                f"got '{returned_incident}'"
            )

        # Validate that required incident contract fields are present
        _validate_incident_fields(data)

        return data

    async def health_check(self) -> bool:
        """Check if Phase 4 API is reachable."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self._base_url}/health")
                return response.status_code == 200
        except Exception:
            return False
