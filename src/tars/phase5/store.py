"""
Redis Reasoning Store
=====================
Async Redis operations for reading and writing reasoning analyses.

Key design:
- tars:mission:{mission_id}:reasoning:analyses → hash (field=incident_id, value=JSON)

Uses redis.asyncio for non-blocking I/O.
Reuses the same Redis instance as Phases 3 and 4.
"""

from __future__ import annotations

import json
import logging
from typing import Optional

import redis.asyncio as aioredis

from .config import settings
from .models import ReasoningResult

logger = logging.getLogger("phase5.store")


class ReasoningStore:
    """
    Async Redis store for reasoning analyses.

    Stores one current analysis per incident in a hash keyed by mission.
    """

    def __init__(self, redis_url: Optional[str] = None) -> None:
        self._redis_url = redis_url or settings.REDIS_URL
        self._redis: Optional[aioredis.Redis] = None

    async def connect(self) -> None:
        """Establish Redis connection."""
        if self._redis is None:
            self._redis = aioredis.from_url(
                self._redis_url,
                decode_responses=True,
            )

    async def close(self) -> None:
        """Close Redis connection."""
        if self._redis is not None:
            await self._redis.aclose()
            self._redis = None

    async def ping(self) -> bool:
        """Check Redis connectivity."""
        try:
            await self.connect()
            assert self._redis is not None
            return await self._redis.ping()
        except Exception:
            return False

    @property
    def redis(self) -> aioredis.Redis:
        """Get the Redis client, raising if not connected."""
        if self._redis is None:
            raise RuntimeError(
                "ReasoningStore not connected. Call connect() first."
            )
        return self._redis

    # -----------------------------------------------------------------------
    # Key helpers
    # -----------------------------------------------------------------------

    def _key(self, mission_id: str) -> str:
        """Build the Redis hash key for a mission's reasoning analyses."""
        return (
            f"{settings.REDIS_KEY_PREFIX}:{mission_id}:reasoning:analyses"
        )

    # -----------------------------------------------------------------------
    # Save / Get / List / Clear
    # -----------------------------------------------------------------------

    async def save_analysis(
        self,
        mission_id: str,
        incident_id: str,
        result: ReasoningResult,
    ) -> None:
        """
        Save or replace a reasoning analysis for an incident.

        Args:
            mission_id: Mission identifier.
            incident_id: Incident identifier (hash field).
            result: Validated reasoning result to persist.
        """
        key = self._key(mission_id)
        value = result.model_dump_json()
        await self.redis.hset(key, incident_id, value)
        logger.info(
            "Saved reasoning analysis for incident '%s' in mission '%s'",
            incident_id,
            mission_id,
        )

    async def get_analysis(
        self,
        mission_id: str,
        incident_id: str,
    ) -> Optional[ReasoningResult]:
        """
        Get the current reasoning analysis for an incident.

        Args:
            mission_id: Mission identifier.
            incident_id: Incident identifier.

        Returns:
            ReasoningResult if found, None otherwise.
        """
        key = self._key(mission_id)
        raw = await self.redis.hget(key, incident_id)

        if raw is None:
            return None

        try:
            return ReasoningResult.model_validate_json(raw)
        except Exception as exc:
            logger.warning(
                "Failed to parse reasoning analysis for '%s': %s",
                incident_id,
                exc,
            )
            return None

    async def list_analyses(
        self,
        mission_id: str,
    ) -> list[ReasoningResult]:
        """
        List all reasoning analyses for a mission.

        Args:
            mission_id: Mission identifier.

        Returns:
            List of ReasoningResult objects.
        """
        key = self._key(mission_id)
        raw_map = await self.redis.hgetall(key)

        analyses: list[ReasoningResult] = []
        for incident_id, raw_value in raw_map.items():
            try:
                result = ReasoningResult.model_validate_json(raw_value)
                analyses.append(result)
            except Exception as exc:
                logger.warning(
                    "Failed to parse reasoning analysis for '%s': %s",
                    incident_id,
                    exc,
                )

        # Sort by created_at for consistent ordering
        analyses.sort(key=lambda r: r.created_at)
        return analyses

    async def clear_analyses(self, mission_id: str) -> None:
        """Delete all reasoning analyses for a mission."""
        key = self._key(mission_id)
        await self.redis.delete(key)
        logger.info(
            "Cleared all reasoning analyses for mission '%s'",
            mission_id,
        )
