"""
Phase 9 Evaluation Client
===========================
Read-only HTTP client for fetching Phase 9 evaluation summaries
and metric labels for learning evidence.

Phase 9 is required for meaningful learning runs. Its unavailability
should fail the learning run with a clear error.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import httpx

from ..config import settings

logger = logging.getLogger("phase10.adapters.phase9")


class Phase9ClientError(Exception):
    """Error communicating with Phase 9 API."""


class Phase9UnavailableError(Phase9ClientError):
    """Phase 9 API is unavailable."""


class Phase9Client:
    """
    Async HTTP client for Phase 9 Evaluation API.

    Reads evaluation summaries and metric labels for learning evidence.
    Phase 9 is required; unavailability fails the learning run.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> None:
        self._base_url = (base_url or settings.PHASE9_API_URL).rstrip("/")
        self._timeout = timeout or settings.LEARNING_CLIENT_TIMEOUT

    async def get_evaluations_by_mission(
        self,
        mission_id: str,
    ) -> list[dict[str, Any]]:
        """
        Get all evaluations for a mission.

        Returns a list of evaluation summary dicts.
        """
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.get(
                    f"{self._base_url}/api/v1/evaluations/mission/{mission_id}"
                )
                if resp.status_code == 404:
                    return []
                resp.raise_for_status()
                data = resp.json()
                return data.get("evaluations", [])
        except httpx.ConnectError as exc:
            raise Phase9UnavailableError(
                f"Phase 9 API unreachable: {exc}"
            ) from exc
        except Exception as exc:
            logger.warning("Phase 9 API error: %s", exc)
            raise Phase9ClientError(
                f"Phase 9 API error: {exc}"
            ) from exc

    async def get_evaluation(
        self,
        evaluation_id: str,
    ) -> Optional[dict[str, Any]]:
        """
        Get a single evaluation by ID.

        Returns evaluation dict or None if not found.
        """
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.get(
                    f"{self._base_url}/api/v1/evaluations/{evaluation_id}"
                )
                if resp.status_code == 404:
                    return None
                resp.raise_for_status()
                return resp.json()
        except httpx.ConnectError as exc:
            raise Phase9UnavailableError(
                f"Phase 9 API unreachable: {exc}"
            ) from exc
        except Exception as exc:
            logger.warning("Phase 9 API error: %s", exc)
            return None

    async def list_all_evaluations(
        self,
        mission_ids: Optional[list[str]] = None,
        since: Optional[str] = None,
        until: Optional[str] = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """
        List evaluations across missions with optional filters.

        If mission_ids is provided, fetches evaluations for each mission
        via the Phase 9 API.  When mission_ids is *not* provided, discovers
        recent missions from the Phase 9 API's ``/api/v1/evaluations/recent``
        endpoint (if available) or falls back to querying the shared
        PostgreSQL ``evaluations`` table directly.
        """
        all_evaluations: list[dict[str, Any]] = []

        if not mission_ids:
            # Try the recent-evaluations endpoint first
            try:
                recent = await self._fetch_recent_evaluations(
                    since=since, until=until, limit=limit,
                )
                if recent is not None:
                    return recent
            except Exception as exc:
                logger.debug(
                    "Recent evaluations endpoint unavailable: %s", exc,
                )

            # Fallback: discover distinct missions from the shared DB
            mission_ids = await self._discover_recent_missions(
                since=since, until=until, limit=limit,
            )
            if not mission_ids:
                return all_evaluations

        for mission_id in mission_ids[:limit]:
            try:
                evals = await self.get_evaluations_by_mission(mission_id)
                # Apply date filters if provided
                for ev in evals:
                    created_at = ev.get("created_at", "")
                    if since and created_at < since:
                        continue
                    if until and created_at > until:
                        continue
                    all_evaluations.append(ev)
                    if len(all_evaluations) >= limit:
                        break
            except Phase9UnavailableError:
                raise
            except Exception as exc:
                logger.warning(
                    "Failed to fetch evaluations for mission '%s': %s",
                    mission_id,
                    exc,
                )

            if len(all_evaluations) >= limit:
                break

        return all_evaluations[:limit]

    async def _fetch_recent_evaluations(
        self,
        since: Optional[str] = None,
        until: Optional[str] = None,
        limit: int = 100,
    ) -> Optional[list[dict[str, Any]]]:
        """
        Try to fetch recent evaluations from a bulk endpoint.

        Returns None if the endpoint does not exist (404).
        """
        params: dict[str, Any] = {"limit": limit}
        if since:
            params["since"] = since
        if until:
            params["until"] = until

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.get(
                f"{self._base_url}/api/v1/evaluations/recent",
                params=params,
            )
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            data = resp.json()
            return data.get("evaluations", [])

    async def _discover_recent_missions(
        self,
        since: Optional[str] = None,
        until: Optional[str] = None,
        limit: int = 100,
    ) -> list[str]:
        """
        Discover distinct mission IDs from the shared PostgreSQL database.

        Falls back to an empty list if the database is unreachable.
        """
        try:
            from sqlalchemy import text
            from ..database import get_session

            async for session in get_session():
                query = text(
                    "SELECT DISTINCT mission_id FROM evaluations "
                    "WHERE 1=1 "
                    + ("AND created_at >= :since " if since else "")
                    + ("AND created_at <= :until " if until else "")
                    + "ORDER BY mission_id LIMIT :limit"
                )
                params: dict[str, Any] = {"limit": limit}
                if since:
                    params["since"] = since
                if until:
                    params["until"] = until

                result = await session.execute(query, params)
                return [row[0] for row in result.fetchall()]
        except Exception as exc:
            logger.warning(
                "Failed to discover missions from database: %s", exc,
            )
            return []

    async def health_check(self) -> bool:
        """Check Phase 9 API connectivity."""
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                resp = await client.get(f"{self._base_url}/health")
                return resp.status_code < 500
        except Exception:
            return False
