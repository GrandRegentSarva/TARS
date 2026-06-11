"""
Incident Service
================
Orchestrates incident detection and querying.

Service flow:
1. Set status to processing.
2. Fetch Phase 3 state timeline.
3. Run detector (evaluate rules + collapse into incidents).
4. Write incidents to Redis.
5. Set status to complete.
6. On failure, set status to failed.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from .config import settings
from .detector import detect_incidents
from .models import (
    Incident,
    IncidentListResponse,
    ProcessingStatus,
    ProcessingStatusResponse,
    ProcessResponse,
)
from .state_client import StateClient
from .store import IncidentStore

logger = logging.getLogger("phase4.service")


class IncidentService:
    """
    Orchestrates incident detection from Phase 3 state timelines.

    Coordinates between the state client, detector, and Redis store.
    """

    def __init__(
        self,
        store: IncidentStore,
        state_client: StateClient,
    ) -> None:
        self._store = store
        self._state_client = state_client

    async def process_mission(
        self,
        mission_id: str,
        from_ms: int = 0,
        to_ms: Optional[int] = None,
        overwrite: bool = True,
    ) -> ProcessResponse:
        """
        Detect incidents for a mission by consuming Phase 3 state timeline.

        Args:
            mission_id: Mission identifier.
            from_ms: Start elapsed_ms for state timeline.
            to_ms: End elapsed_ms for state timeline. None = all.
            overwrite: If True, replace existing incidents.

        Returns:
            ProcessResponse with detection results.
        """
        started_at = datetime.now(timezone.utc).isoformat()

        # Set status to processing
        await self._store.set_status(
            mission_id,
            ProcessingStatus.PROCESSING,
            started_at=started_at,
        )

        try:
            # Fetch state timeline from Phase 3
            logger.info(
                "Fetching state timeline for mission '%s' (from_ms=%d, to_ms=%s)",
                mission_id, from_ms, to_ms,
            )
            timeline_data = await self._state_client.get_timeline(
                mission_id=mission_id,
                from_ms=from_ms,
                to_ms=to_ms,
            )

            states = timeline_data.get("states", [])
            states_evaluated = len(states)

            logger.info(
                "Received %d states for mission '%s'",
                states_evaluated, mission_id,
            )

            # Run incident detection
            incidents = detect_incidents(
                states=states,
                mission_id=mission_id,
            )

            incidents_detected = len(incidents)
            logger.info(
                "Detected %d incidents for mission '%s'",
                incidents_detected, mission_id,
            )

            # Write incidents to Redis
            if overwrite:
                await self._store.replace_incidents(mission_id, incidents)
            else:
                # Only write if no existing incidents
                existing = await self._store.get_incidents(mission_id)
                if not existing:
                    await self._store.replace_incidents(mission_id, incidents)
                else:
                    logger.info(
                        "Skipping write: %d existing incidents for '%s'",
                        len(existing), mission_id,
                    )

            # Set status to complete
            completed_at = datetime.now(timezone.utc).isoformat()
            await self._store.set_status(
                mission_id,
                ProcessingStatus.COMPLETE,
                states_evaluated=str(states_evaluated),
                incidents_detected=str(incidents_detected),
                completed_at=completed_at,
            )

            return ProcessResponse(
                mission_id=mission_id,
                states_evaluated=states_evaluated,
                incidents_detected=incidents_detected,
                status="complete",
            )

        except Exception as exc:
            logger.error(
                "Failed to process incidents for mission '%s': %s",
                mission_id, exc,
            )
            completed_at = datetime.now(timezone.utc).isoformat()
            await self._store.set_status(
                mission_id,
                ProcessingStatus.FAILED,
                completed_at=completed_at,
                error=str(exc),
            )
            raise

    async def get_incidents(
        self,
        mission_id: str,
        from_ms: int = 0,
        to_ms: Optional[int] = None,
    ) -> IncidentListResponse:
        """Get incidents for a mission within a time range."""
        incidents = await self._store.get_incidents(mission_id, from_ms, to_ms)
        return IncidentListResponse(
            mission_id=mission_id,
            incidents=incidents,
            total=len(incidents),
            from_ms=from_ms,
            to_ms=to_ms,
        )

    async def get_incident(
        self, mission_id: str, incident_id: str
    ) -> Optional[Incident]:
        """Get a specific incident by ID."""
        return await self._store.get_incident(mission_id, incident_id)

    async def get_processing_status(
        self, mission_id: str
    ) -> ProcessingStatusResponse:
        """Get processing status for a mission."""
        meta = await self._store.get_status(mission_id)

        if not meta:
            return ProcessingStatusResponse(
                mission_id=mission_id,
                status=ProcessingStatus.NOT_STARTED,
            )

        status_str = meta.get("status", "not_started")
        try:
            status = ProcessingStatus(status_str)
        except ValueError:
            status = ProcessingStatus.NOT_STARTED

        return ProcessingStatusResponse(
            mission_id=mission_id,
            status=status,
            states_evaluated=int(meta.get("states_evaluated", "0")),
            incidents_detected=int(meta.get("incidents_detected", "0")),
            started_at=meta.get("started_at"),
            completed_at=meta.get("completed_at"),
            error=meta.get("error"),
        )
