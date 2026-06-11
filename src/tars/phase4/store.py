"""
Redis Incident Store
====================
Async Redis operations for reading and writing mission incidents.

Key design:
- tars:mission:{mission_id}:incidents:timeline  → sorted set (score=start_ms, value=JSON)
- tars:mission:{mission_id}:incidents:meta       → hash with processing metadata

Uses redis.asyncio for non-blocking I/O.
Reuses the same Redis instance as Phase 3.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Optional

import redis.asyncio as aioredis

from .config import settings
from .models import Incident, ProcessingStatus

logger = logging.getLogger("phase4.store")


class IncidentStore:
    """
    Async Redis store for mission incidents.

    Manages incident timeline (sorted set) and processing metadata.
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
            raise RuntimeError("IncidentStore not connected. Call connect() first.")
        return self._redis

    # -----------------------------------------------------------------------
    # Key helpers
    # -----------------------------------------------------------------------

    def _key(self, mission_id: str, suffix: str) -> str:
        """Build a Redis key."""
        return f"{settings.REDIS_KEY_PREFIX}:{mission_id}:incidents:{suffix}"

    # -----------------------------------------------------------------------
    # Incident Timeline
    # -----------------------------------------------------------------------

    async def replace_incidents(
        self, mission_id: str, incidents: list[Incident]
    ) -> None:
        """
        Replace all incidents for a mission.

        Deletes existing timeline and writes new incidents atomically.
        """
        key = self._key(mission_id, "timeline")
        pipe = self.redis.pipeline()
        pipe.delete(key)
        for incident in incidents:
            pipe.zadd(key, {incident.model_dump_json(): incident.start_ms})
        await pipe.execute()

    async def get_incidents(
        self,
        mission_id: str,
        from_ms: int = 0,
        to_ms: Optional[int] = None,
    ) -> list[Incident]:
        """
        Read incidents from the timeline within a time range.

        Args:
            mission_id: Mission identifier.
            from_ms: Start time (inclusive).
            to_ms: End time (inclusive). None = +inf.

        Returns:
            Ordered list of Incidents by start_ms.
        """
        key = self._key(mission_id, "timeline")
        max_score = to_ms if to_ms is not None else "+inf"

        raw_items = await self.redis.zrangebyscore(
            key,
            min=from_ms,
            max=max_score,
        )

        incidents: list[Incident] = []
        for item in raw_items:
            try:
                incidents.append(Incident.model_validate_json(item))
            except Exception as exc:
                logger.warning("Failed to parse incident entry: %s", exc)

        return incidents

    async def get_incident(
        self, mission_id: str, incident_id: str
    ) -> Optional[Incident]:
        """
        Get a specific incident by ID.

        Scans the timeline sorted set for a matching incident_id.
        """
        key = self._key(mission_id, "timeline")
        raw_items = await self.redis.zrangebyscore(key, min=0, max="+inf")

        for item in raw_items:
            try:
                incident = Incident.model_validate_json(item)
                if incident.incident_id == incident_id:
                    return incident
            except Exception:
                continue

        return None

    # -----------------------------------------------------------------------
    # Processing Metadata
    # -----------------------------------------------------------------------

    async def set_status(
        self,
        mission_id: str,
        status: ProcessingStatus,
        **fields: str,
    ) -> None:
        """
        Update processing metadata for a mission.

        Args:
            mission_id: Mission identifier.
            status: Processing status.
            **fields: Additional hash fields.
        """
        key = self._key(mission_id, "meta")
        mapping = {"status": status.value, **fields}
        await self.redis.hset(key, mapping=mapping)

    async def get_status(self, mission_id: str) -> dict[str, str]:
        """Read processing metadata for a mission."""
        key = self._key(mission_id, "meta")
        data = await self.redis.hgetall(key)
        return data or {}

    # -----------------------------------------------------------------------
    # Cleanup
    # -----------------------------------------------------------------------

    async def clear_incidents(self, mission_id: str) -> None:
        """Delete all incident data for a mission from Redis."""
        keys = [
            self._key(mission_id, "timeline"),
            self._key(mission_id, "meta"),
        ]
        await self.redis.delete(*keys)
