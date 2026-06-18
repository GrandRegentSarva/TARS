"""
Phase 5 Reasoning Client
==========================
Read-only HTTP client for fetching Phase 5 reasoning results.

Reads advisory reasoning outputs and metadata without invoking
the Gemini provider or any reasoning generation.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import httpx

from ..config import settings

logger = logging.getLogger("phase9.adapters.phase5")


class Phase5ClientError(Exception):
    """Error communicating with Phase 5 API."""


class Phase5NotFoundError(Phase5ClientError):
    """Reasoning result not found in Phase 5."""


class Phase5UnavailableError(Phase5ClientError):
    """Phase 5 API is unavailable."""


class Phase5Client:
    """
    Async HTTP client for Phase 5 Reasoning API.

    Reads reasoning results for evaluation. Never invokes Gemini.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> None:
        self._base_url = (base_url or settings.PHASE5_API_URL).rstrip("/")
        self._timeout = timeout or settings.EVALUATION_CLIENT_TIMEOUT

    async def get_reasoning(
        self,
        mission_id: str,
        incident_id: str,
    ) -> Optional[dict[str, Any]]:
        """
        Get a reasoning result for a specific incident.

        Returns:
            Reasoning result dict or None if not found.

        Raises:
            Phase5ClientError: On communication failure.
        """
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.get(
                    f"{self._base_url}/api/v1/reasoning/{mission_id}/{incident_id}"
                )
                if resp.status_code == 404:
                    return None
                resp.raise_for_status()
                return resp.json()
        except httpx.HTTPStatusError as exc:
            raise Phase5ClientError(
                f"Phase 5 API error: {exc.response.status_code}"
            ) from exc
        except httpx.ConnectError as exc:
            raise Phase5UnavailableError(
                f"Phase 5 API unreachable: {exc}"
            ) from exc
        except Exception as exc:
            raise Phase5ClientError(
                f"Phase 5 API error: {exc}"
            ) from exc

    async def get_reasoning_by_id(
        self,
        reasoning_id: str,
        mission_id: str,
    ) -> Optional[dict[str, Any]]:
        """
        Get a reasoning result by reasoning_id.

        Fetches all analyses for the mission and finds the matching one.

        Returns:
            Reasoning result dict or None if not found.
        """
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.get(
                    f"{self._base_url}/api/v1/reasoning/{mission_id}"
                )
                if resp.status_code == 404:
                    return None
                resp.raise_for_status()
                data = resp.json()
                analyses = data.get("analyses", [])
                for analysis in analyses:
                    if analysis.get("reasoning_id") == reasoning_id:
                        return analysis
                return None
        except httpx.ConnectError as exc:
            raise Phase5UnavailableError(
                f"Phase 5 API unreachable: {exc}"
            ) from exc
        except Exception as exc:
            raise Phase5ClientError(
                f"Phase 5 API error: {exc}"
            ) from exc

    async def list_analyses(
        self,
        mission_id: str,
    ) -> list[dict[str, Any]]:
        """
        List all reasoning analyses for a mission.

        Returns:
            List of reasoning result dicts.
        """
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.get(
                    f"{self._base_url}/api/v1/reasoning/{mission_id}"
                )
                if resp.status_code == 404:
                    return []
                resp.raise_for_status()
                data = resp.json()
                return data.get("analyses", [])
        except httpx.ConnectError as exc:
            raise Phase5UnavailableError(
                f"Phase 5 API unreachable: {exc}"
            ) from exc
        except Exception as exc:
            raise Phase5ClientError(
                f"Phase 5 API error: {exc}"
            ) from exc

    async def health_check(self) -> bool:
        """Check Phase 5 API connectivity."""
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                resp = await client.get(f"{self._base_url}/health")
                return resp.status_code < 500
        except Exception:
            return False
