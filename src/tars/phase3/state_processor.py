"""
State Processor
===============
Orchestrates frame-to-state conversion.

Takes a single telemetry frame (from Phase 2 replay) and produces
a StateSnapshot by combining:
- Phase classification
- Health assessment
- Risk scoring
- Signal quality indicators
- Derived metrics

This module is pure Python with no I/O dependencies, making it
easy to unit test.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from .models import (
    MissionPhase,
    StateMetrics,
    StateSnapshot,
    TelemetryFrame,
)
from .phase_classifier import classify_phase
from .risk import (
    compute_health,
    compute_risk,
    compute_signals,
    extract_metrics,
)

logger = logging.getLogger("phase3.state_processor")


class StateProcessor:
    """
    Stateful processor that converts telemetry frames into state snapshots.

    Maintains minimal state between frames (previous altitude) for
    trend-based classification rules.
    """

    def __init__(self, mission_id: str) -> None:
        self.mission_id = mission_id
        self._prev_altitude: Optional[float] = None

    def process_frame(self, frame: TelemetryFrame) -> StateSnapshot:
        """
        Process a single telemetry frame into a state snapshot.

        Args:
            frame: A TelemetryFrame from Phase 2 replay.

        Returns:
            A fully computed StateSnapshot.
        """
        telemetry = frame.telemetry

        # Step 1: Extract numeric metrics
        metrics = extract_metrics(telemetry)

        # Step 2: Classify mission phase
        phase = classify_phase(telemetry, self._prev_altitude)

        # Step 3: Compute signal quality
        signals = compute_signals(telemetry, metrics, phase)

        # Step 4: Compute health status
        health, health_reasons = compute_health(telemetry, metrics, phase)

        # Step 5: Compute risk score
        risk, risk_reasons = compute_risk(telemetry, metrics, phase)

        # Merge reasons (deduplicate while preserving order)
        all_reasons = _merge_reasons(health_reasons, risk_reasons)

        # Update state for next frame
        if metrics.relative_altitude_m is not None:
            self._prev_altitude = metrics.relative_altitude_m

        return StateSnapshot(
            mission_id=self.mission_id,
            sequence=frame.sequence,
            timestamp=frame.timestamp,
            elapsed_ms=frame.elapsed_ms,
            phase=phase,
            health=health,
            risk=risk,
            signals=signals,
            metrics=metrics,
            reasons=all_reasons,
        )

    def reset(self) -> None:
        """Reset processor state for reprocessing."""
        self._prev_altitude = None


def process_frames(
    mission_id: str,
    frames: list[TelemetryFrame],
) -> list[StateSnapshot]:
    """
    Process a list of telemetry frames into state snapshots.

    Convenience function for batch processing.

    Args:
        mission_id: The mission identifier.
        frames: Ordered list of TelemetryFrames.

    Returns:
        Ordered list of StateSnapshots.
    """
    processor = StateProcessor(mission_id)
    snapshots: list[StateSnapshot] = []

    for frame in frames:
        try:
            snapshot = processor.process_frame(frame)
            snapshots.append(snapshot)
        except Exception as exc:
            logger.error(
                "Failed to process frame %d for mission %s: %s",
                frame.sequence,
                mission_id,
                exc,
            )
            # Continue processing remaining frames
            continue

    return snapshots


def _merge_reasons(
    health_reasons: list[str],
    risk_reasons: list[str],
) -> list[str]:
    """Merge reason lists, deduplicating while preserving order."""
    seen: set[str] = set()
    merged: list[str] = []

    for reason in health_reasons + risk_reasons:
        if reason not in seen:
            seen.add(reason)
            merged.append(reason)

    return merged
