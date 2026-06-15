"""
Phase 5 Reasoning Client
=========================
Async HTTP client for consuming Phase 5 reasoning data.

Fetches reasoning analysis lists for a mission for graph projection.
Validates required fields and cross-phase identifiers.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import httpx

from .config import settings

logger = logging.getLogger("phase7.phase5_client")

# Required fields for a valid Phase 5 reasoning result contract.
_REQUIRED_REASONING_FIELDS = [
    "reasoning_id",
    "mission_id",
    "incident_id",
    "root_cause",
    "confidence",
    "recommendation",
    "model",
    "prompt_version",
    "rationale",
    "created_at",
]


class Phase5ClientError(Exception):
    """Base error for Phase 5 client failures."""
    pass


class Phase5UnavailableError(Phase5ClientError):
    """Phase 5 API is unreachable or returned a server error."""
    pass


class Phase5Client:
    """
    HTTP client for the Phase 5 Gemini Reasoning API.

    Fetches reasoning analysis lists for graph projection.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> None:
        self._base_url = (base_url or settings.PHASE5_API_URL).rstrip("/")
        self._timeout = timeout or settings.MEMORY_CLIENT_TIMEOUT

    async def get_analyses(self, mission_id: str) -> list[dict[str, Any]]:
        """
        Fetch all reasoning analyses for a mission from Phase 5.

        Args:
            mission_id: Mission identifier.

        Returns:
            List of reasoning result dicts.

        Raises:
            Phase5UnavailableError: If Phase 5 is unreachable.
            ValueError: If any analysis is missing required fields or
                       has a mission_id mismatch.
        """
        url = f"{self._base_url}/api/v1/reasoning/{mission_id}"

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.get(url)
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            raise Phase5UnavailableError(
                f"Phase 5 API unreachable at {self._base_url}: {exc}"
            ) from exc
        except httpx.TimeoutException as exc:
            raise Phase5UnavailableError(
                f"Phase 5 API timeout: {exc}"
            ) from exc

        if response.status_code >= 500:
            raise Phase5UnavailableError(
                f"Phase 5 API server error: {response.status_code}"
            )

        if response.status_code == 404:
            # No analyses for this mission is valid
            logger.info(
                "No analyses found for mission '%s' in Phase 5",
                mission_id,
            )
            return []

        if response.status_code >= 400:
            raise Phase5ClientError(
                f"Phase 5 API client error: {response.status_code}"
            )

        data = response.json()
        analyses = data.get("analyses", [])

        # Validate each analysis
        validated = []
        for analysis in analyses:
            self._validate_analysis(analysis, mission_id)
            validated.append(analysis)

        logger.info(
            "Fetched %d analyses for mission '%s' from Phase 5",
            len(validated),
            mission_id,
        )
        return validated

    def _validate_analysis(
        self,
        analysis: dict[str, Any],
        expected_mission_id: str,
    ) -> None:
        """
        Validate a single reasoning analysis dict.

        Raises:
            ValueError: If required fields are missing or identifiers mismatch.
        """
        missing = [
            f for f in _REQUIRED_REASONING_FIELDS
            if f not in analysis or analysis[f] is None
        ]
        if missing:
            raise ValueError(
                f"Phase 5 analysis missing required fields: "
                f"{', '.join(missing)}"
            )

        if analysis.get("mission_id") != expected_mission_id:
            raise ValueError(
                f"Analysis mission_id mismatch: expected '{expected_mission_id}', "
                f"got '{analysis.get('mission_id')}'"
            )

    async def health_check(self) -> bool:
        """Check if Phase 5 API is reachable."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self._base_url}/health")
                return response.status_code == 200
        except Exception:
            return False
