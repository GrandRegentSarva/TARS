"""
Phase 7 Operational Memory Client
===================================
Read-only HTTP client for fetching Phase 7 incident neighborhoods,
mitigations, outcomes, and similar history for learning evidence.

Phase 7 is optional. Its unavailability produces warnings, not crashes.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import httpx

from ..config import settings

logger = logging.getLogger("phase10.adapters.phase7")


class Phase7ClientError(Exception):
    """Error communicating with Phase 7 API."""


class Phase7UnavailableError(Phase7ClientError):
    """Phase 7 API is unavailable."""


class Phase7Client:
    """
    Async HTTP client for Phase 7 Operational Memory API.

    Reads incident neighborhoods, mitigations, and outcomes for
    learning evidence. Phase 7 is optional; unavailability is
    handled gracefully with warnings.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> None:
        self._base_url = (base_url or settings.PHASE7_API_URL).rstrip("/")
        self._timeout = timeout or settings.LEARNING_CLIENT_TIMEOUT

    async def get_incident_memory(
        self,
        incident_id: str,
    ) -> Optional[dict[str, Any]]:
        """
        Get incident neighborhood from Phase 7 graph.

        Returns incident facts, root causes, mitigations, and outcomes.
        """
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.get(
                    f"{self._base_url}/api/v1/memory/incidents/{incident_id}"
                )
                if resp.status_code == 404:
                    return None
                resp.raise_for_status()
                return resp.json()
        except httpx.ConnectError as exc:
            logger.warning("Phase 7 API unreachable: %s", exc)
            return None
        except Exception as exc:
            logger.warning("Phase 7 API error: %s", exc)
            return None

    async def get_mission_outcomes(
        self,
        mission_id: str,
    ) -> Optional[dict[str, Any]]:
        """
        Get mission-level outcomes from Phase 7.

        Returns mission sync data including outcomes and mitigations.
        """
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.get(
                    f"{self._base_url}/api/v1/memory/sync/{mission_id}"
                )
                if resp.status_code == 404:
                    return None
                resp.raise_for_status()
                return resp.json()
        except httpx.ConnectError as exc:
            logger.warning("Phase 7 API unreachable: %s", exc)
            return None
        except Exception as exc:
            logger.warning("Phase 7 API error: %s", exc)
            return None

    async def get_similar_incidents(
        self,
        incident_type: str,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """
        Get similar incidents from Phase 7 for pattern context.

        Returns a list of similar incident summaries.
        """
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.get(
                    f"{self._base_url}/api/v1/memory/similar",
                    params={
                        "incident_type": incident_type,
                        "limit": limit,
                    },
                )
                if resp.status_code == 404:
                    return []
                resp.raise_for_status()
                data = resp.json()
                return data.get("incidents", data) if isinstance(data, dict) else data
        except httpx.ConnectError as exc:
            logger.warning("Phase 7 API unreachable: %s", exc)
            return []
        except Exception as exc:
            logger.warning("Phase 7 API error: %s", exc)
            return []

    async def health_check(self) -> bool:
        """Check Phase 7 API connectivity."""
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                resp = await client.get(f"{self._base_url}/health")
                return resp.status_code < 500
        except Exception:
            return False
