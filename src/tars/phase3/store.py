"""
Redis State Store
=================
Async Redis operations for reading and writing mission state.

Key design:
- tars:mission:{mission_id}:state:current   → latest state snapshot (string JSON)
- tars:mission:{mission_id}:state:timeline  → sorted set (score=elapsed_ms, value=JSON)
- tars:mission:{mission_id}:state:meta      → hash with processing metadata

Uses redis.asyncio for non-blocking I/O.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Optional

import redis.asyncio as aioredis

from .config import settings
from .models import ProcessingStatus, StateSnapshot

logger = logging.getLogger("phase3.store")


class StateStore:
    """
    Async Redis store for mission state snapshots.

    Manages current state, timeline (sorted set), and processing metadata.
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
            raise RuntimeError("StateStore not connected. Call connect() first.")
        return self._redis

    # -----------------------------------------------------------------------
    # Key helpers
    # -----------------------------------------------------------------------

    def _key(self, mission_id: str, suffix: str) -> str:
        """Build a Redis key."""
        return f"{settings.REDIS_KEY_PREFIX}:{mission_id}:state:{suffix}"

    # -----------------------------------------------------------------------
    # Current State
    # -----------------------------------------------------------------------

    async def set_current_state(
        self, mission_id: str, state: StateSnapshot
    ) -> None:
        """Write the latest state snapshot for a mission."""
        key = self._key(mission_id, "current")
        await self.redis.set(key, state.model_dump_json())

    async def get_current_state(
        self, mission_id: str
    ) -> Optional[StateSnapshot]:
        """Read the latest state snapshot for a mission."""
        key = self._key(mission_id, "current")
        data = await self.redis.get(key)
        if data is None:
            return None
        return StateSnapshot.model_validate_json(data)

    # -----------------------------------------------------------------------
    # State Timeline (sorted set)
    # -----------------------------------------------------------------------

    async def append_state(
        self, mission_id: str, state: StateSnapshot
    ) -> None:
        """
        Append a state snapshot to the timeline sorted set.

        Score is a composite of elapsed_ms and sequence to ensure stable
        ordering when multiple frames share the same millisecond:
        score = elapsed_ms + (sequence / 1_000_000)
        """
        key = self._key(mission_id, "timeline")
        score = state.elapsed_ms + (state.sequence / 1_000_000)
        await self.redis.zadd(
            key,
            {state.model_dump_json(): score},
        )

    async def get_timeline(
        self,
        mission_id: str,
        from_ms: int = 0,
        to_ms: Optional[int] = None,
        limit: int = 1000,
    ) -> list[StateSnapshot]:
        """
        Read state snapshots from the timeline within a time range.

        Args:
            mission_id: Mission identifier.
            from_ms: Start elapsed_ms (inclusive).
            to_ms: End elapsed_ms (inclusive). None = +inf.
            limit: Maximum number of snapshots to return.

        Returns:
            Ordered list of StateSnapshots.
        """
        key = self._key(mission_id, "timeline")
        # Add 0.999999 to to_ms to include all sequence tiebreakers
        # within the target millisecond (scores are elapsed_ms + seq/1M)
        if to_ms is not None:
            max_score = to_ms + 0.999999
        else:
            max_score = "+inf"

        raw_items = await self.redis.zrangebyscore(
            key,
            min=from_ms,
            max=max_score,
            start=0,
            num=limit,
        )

        snapshots: list[StateSnapshot] = []
        for item in raw_items:
            try:
                snapshots.append(StateSnapshot.model_validate_json(item))
            except Exception as exc:
                logger.warning("Failed to parse timeline entry: %s", exc)

        return snapshots

    async def get_state_at(
        self, mission_id: str, elapsed_ms: int
    ) -> Optional[StateSnapshot]:
        """
        Get the nearest state snapshot at or before elapsed_ms.

        Uses ZREVRANGEBYSCORE to find the latest entry <= elapsed_ms.
        """
        key = self._key(mission_id, "timeline")
        # Add 0.999999 to include all sequence tiebreakers within
        # the target millisecond (scores are elapsed_ms + seq/1M)
        max_score = elapsed_ms + 0.999999

        items = await self.redis.zrevrangebyscore(
            key,
            max=max_score,
            min=0,
            start=0,
            num=1,
        )

        if not items:
            return None

        return StateSnapshot.model_validate_json(items[0])

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
            **fields: Additional hash fields (frames_processed, error, etc.)
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

    async def clear_mission_state(self, mission_id: str) -> None:
        """Delete all state data for a mission from Redis."""
        keys = [
            self._key(mission_id, "current"),
            self._key(mission_id, "timeline"),
            self._key(mission_id, "meta"),
        ]
        await self.redis.delete(*keys)
