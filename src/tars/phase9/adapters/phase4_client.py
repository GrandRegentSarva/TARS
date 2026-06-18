"""
Phase 4 Incident Client
========================
Read-only HTTP client for fetching Phase 4 incident records.

Never mutates incident data or calls flight-control APIs.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import httpx

from ..config import settings

logger = logging.getLogger("phase9.adapters.phase4")


class Phase4ClientError(Exception):
    """Error communicating with Phase 4 API."""


class Phase4NotFoundError(Phase4ClientError):
    """Incident or mission not found in Phase 4."""


class Phase4Client:
    """
    Async HTTP client for Phase 4 Incident API.

    Reads incident records for evaluation evidence.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> None:
        self._base_url = (base_url or settings.PHASE4_API_URL).rstrip("/")
        self._timeout = timeout or settings.EVALUATION_CLIENT_TIMEOUT

    async def get_incidents(
        self,
        mission_id: str,
    ) -> list[dict[str, Any]]:
        """
        Get all incidents for a mission from Phase 4.

        Returns:
            List of incident dicts.

        Raises:
            Phase4ClientError: On communication failure.
        """
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.get(
                    f"{self._base_url}/api/v1/incidents/{mission_id}"
                )
                if resp.status_code == 404:
                    return []
                resp.raise_for_status()
                data = resp.json()
                return data.get("incidents", [])
        except httpx.HTTPStatusError as exc:
            raise Phase4ClientError(
                f"Phase 4 API error: {exc.response.status_code}"
            ) from exc
        except Exception as exc:
            raise Phase4ClientError(
                f"Phase 4 API unreachable: {exc}"
            ) from exc

    async def get_incident(
        self,
        mission_id: str,
        incident_id: str,
    ) -> Optional[dict[str, Any]]:
        """
        Get a single incident from Phase 4.

        Returns:
            Incident dict or None if not found.
        """
        try:
            incidents = await self.get_incidents(mission_id)
            for inc in incidents:
                if inc.get("incident_id") == incident_id:
                    return inc
            return None
        except Phase4ClientError:
            return None

    async def health_check(self) -> bool:
        """Check Phase 4 API connectivity."""
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                resp = await client.get(f"{self._base_url}/health")
                return resp.status_code < 500
        except Exception:
            return False
