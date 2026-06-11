"""
State Engine Service
====================
Application service that orchestrates state processing and querying.

Coordinates between:
- ReplayClient (fetches frames from Phase 2)
- StateProcessor (converts frames to state snapshots)
- StateStore (reads/writes state to Redis)

This is the main entry point for business logic. The API layer
delegates to this service.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from .models import (
    ProcessingStatus,
    ProcessingStatusResponse,
    ProcessResponse,
    StateSnapshot,
    TimelineResponse,
)
from .replay_client import ReplayClient
from .state_processor import StateProcessor
from .store import StateStore

logger = logging.getLogger("phase3.service")


class StateService:
    """
    Application service for state processing and querying.

    Manages the lifecycle of state computation: fetching replay data,
    processing frames, and storing results in Redis.
    """

    def __init__(
        self,
        store: StateStore,
        replay_client: Optional[ReplayClient] = None,
    ) -> None:
        self.store = store
        self.replay_client = replay_client or ReplayClient()

    async def process_mission(
        self,
        mission_id: str,
        from_ms: int = 0,
        to_ms: Optional[int] = None,
        speed: float = 1.0,
        overwrite: bool = True,
    ) -> ProcessResponse:
        """
        Process a mission replay into state snapshots.

        Flow:
        1. Set processing status to 'processing'.
        2. Optionally clear existing Redis state when overwrite=True.
        3. Fetch replay frames from Phase 2.
        4. Process frames in sequence order.
        5. Write each state snapshot to Redis timeline.
        6. Update current state only if this is a full replay (from_ms==0
           and to_ms is None) or if overwrite is True, to prevent partial
           replays from moving current state backwards in time.
        7. Set processing status to 'complete', 'partial', or 'failed'.
        8. On error, set status to 'failed' with the error message.

        Args:
            mission_id: The mission to process.
            from_ms: Start elapsed_ms for replay.
            to_ms: End elapsed_ms for replay. None = end of mission.
            speed: Playback speed multiplier (metadata only).
            overwrite: Clear existing state before processing.

        Returns:
            ProcessResponse with processing results.
        """
        started_at = datetime.now(timezone.utc).isoformat()
        # Only update current state for full replays or when overwriting,
        # to prevent partial window replays from corrupting current state.
        is_full_replay = (from_ms == 0 and to_ms is None)
        should_update_current = is_full_replay or overwrite

        try:
            # Step 1: Set status to processing
            await self.store.set_status(
                mission_id,
                ProcessingStatus.PROCESSING,
                frames_processed="0",
                frames_failed="0",
                started_at=started_at,
            )

            # Step 2: Optionally clear existing state
            if overwrite:
                await self.store.clear_mission_state(mission_id)
                # Re-set status after clear
                await self.store.set_status(
                    mission_id,
                    ProcessingStatus.PROCESSING,
                    frames_processed="0",
                    frames_failed="0",
                    started_at=started_at,
                )

            # Step 3: Fetch replay frames from Phase 2
            replay = await self.replay_client.fetch_replay(
                mission_id=mission_id,
                from_ms=from_ms,
                to_ms=to_ms,
                speed=speed,
            )

            if not replay.frames:
                await self.store.set_status(
                    mission_id,
                    ProcessingStatus.COMPLETE,
                    frames_processed="0",
                    frames_failed="0",
                    completed_at=datetime.now(timezone.utc).isoformat(),
                )
                return ProcessResponse(
                    mission_id=mission_id,
                    frames_processed=0,
                    frames_failed=0,
                    states_written=0,
                    status="complete",
                )

            # Step 4-6: Process frames and write to Redis
            processor = StateProcessor(mission_id)
            states_written = 0
            frames_failed = 0

            for frame in replay.frames:
                try:
                    snapshot = processor.process_frame(frame)

                    # Write to timeline
                    await self.store.append_state(mission_id, snapshot)

                    # Update current state only for full replays or overwrite
                    if should_update_current:
                        await self.store.set_current_state(mission_id, snapshot)

                    states_written += 1
                except Exception as exc:
                    frames_failed += 1
                    logger.error(
                        "Failed to process frame %d for mission %s: %s",
                        frame.sequence,
                        mission_id,
                        exc,
                    )
                    # Continue processing remaining frames

            # Step 7: Determine final status
            completed_at = datetime.now(timezone.utc).isoformat()
            if frames_failed > 0 and states_written == 0:
                final_status = ProcessingStatus.FAILED
                status_str = "failed"
            elif frames_failed > 0:
                final_status = ProcessingStatus.PARTIAL
                status_str = "partial"
            else:
                final_status = ProcessingStatus.COMPLETE
                status_str = "complete"

            await self.store.set_status(
                mission_id,
                final_status,
                frames_processed=str(states_written),
                frames_failed=str(frames_failed),
                completed_at=completed_at,
            )

            logger.info(
                "Processed mission %s: %d frames → %d states (%d failed) [%s]",
                mission_id,
                len(replay.frames),
                states_written,
                frames_failed,
                status_str,
            )

            return ProcessResponse(
                mission_id=mission_id,
                frames_processed=len(replay.frames),
                frames_failed=frames_failed,
                states_written=states_written,
                status=status_str,
            )

        except Exception as exc:
            # Step 8: Set status to failed
            logger.error(
                "Failed to process mission %s: %s",
                mission_id,
                exc,
            )
            await self.store.set_status(
                mission_id,
                ProcessingStatus.FAILED,
                error=str(exc),
            )
            raise

    async def get_current_state(
        self, mission_id: str
    ) -> Optional[StateSnapshot]:
        """Get the latest state snapshot for a mission."""
        return await self.store.get_current_state(mission_id)

    async def get_timeline(
        self,
        mission_id: str,
        from_ms: int = 0,
        to_ms: Optional[int] = None,
        limit: int = 1000,
    ) -> TimelineResponse:
        """Get state timeline for a mission within a time range."""
        states = await self.store.get_timeline(
            mission_id, from_ms, to_ms, limit
        )
        return TimelineResponse(
            mission_id=mission_id,
            states=states,
            total=len(states),
            from_ms=from_ms,
            to_ms=to_ms,
        )

    async def get_state_at(
        self, mission_id: str, elapsed_ms: int
    ) -> Optional[StateSnapshot]:
        """Get the nearest state snapshot at or before elapsed_ms."""
        return await self.store.get_state_at(mission_id, elapsed_ms)

    async def get_processing_status(
        self, mission_id: str
    ) -> ProcessingStatusResponse:
        """Get processing metadata for a mission."""
        meta = await self.store.get_status(mission_id)

        if not meta:
            return ProcessingStatusResponse(
                mission_id=mission_id,
                status=ProcessingStatus.NOT_STARTED,
            )

        return ProcessingStatusResponse(
            mission_id=mission_id,
            status=ProcessingStatus(meta.get("status", "not_started")),
            frames_processed=int(meta.get("frames_processed", "0")),
            started_at=meta.get("started_at"),
            completed_at=meta.get("completed_at"),
            error=meta.get("error"),
        )
