"""
Reasoning Service
=================
Orchestrates incident retrieval, reasoning, validation, and persistence.

Service flow:
1. Check for existing analysis (if overwrite=false, return it).
2. Fetch the incident from Phase 4.
3. Invoke the reasoning provider.
4. Validate the structured response.
5. Persist and return the result.
6. On failure, do not persist.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from .config import settings
from .incident_client import IncidentClient
from .models import (
    ReasoningAnalysis,
    ReasoningListResponse,
    ReasoningResult,
)
from .prompts import PROMPT_VERSION
from .store import ReasoningStore

logger = logging.getLogger("phase5.service")


class ReasoningService:
    """
    Orchestrates reasoning analysis for Phase 4 incidents.

    Coordinates between the incident client, reasoning provider,
    and Redis store.
    """

    def __init__(
        self,
        store: ReasoningStore,
        incident_client: IncidentClient,
        provider: Any,  # ReasoningProvider protocol
    ) -> None:
        self._store = store
        self._incident_client = incident_client
        self._provider = provider

    async def analyze_incident(
        self,
        mission_id: str,
        incident_id: str,
        overwrite: bool = True,
    ) -> ReasoningResult:
        """
        Analyze a Phase 4 incident through the reasoning provider.

        Args:
            mission_id: Mission identifier.
            incident_id: Incident identifier.
            overwrite: If False, return existing analysis without
                       invoking the provider.

        Returns:
            ReasoningResult with the analysis.

        Raises:
            Various exceptions propagated from client/provider/store.
        """
        # Check for existing analysis when overwrite=false
        if not overwrite:
            existing = await self._store.get_analysis(
                mission_id, incident_id
            )
            if existing is not None:
                logger.info(
                    "Returning existing analysis for incident '%s' "
                    "(overwrite=false)",
                    incident_id,
                )
                return existing

        # Fetch the incident from Phase 4
        logger.info(
            "Fetching incident '%s' from Phase 4 for mission '%s'",
            incident_id,
            mission_id,
        )
        incident = await self._incident_client.get_incident(
            mission_id, incident_id
        )

        # Invoke the reasoning provider
        logger.info(
            "Invoking reasoning provider for incident '%s'",
            incident_id,
        )
        analysis: ReasoningAnalysis = await self._provider.analyze(incident)

        # Build the full result with metadata
        reasoning_id = f"reason_{uuid.uuid4().hex[:12]}"
        now = datetime.now(timezone.utc).isoformat()

        result = ReasoningResult(
            reasoning_id=reasoning_id,
            mission_id=mission_id,
            incident_id=incident_id,
            incident_type=incident.get("incident_type", "unknown"),
            root_cause=analysis.root_cause,
            confidence=analysis.confidence,
            recommendation=analysis.recommendation,
            rationale=analysis.rationale,
            contributing_factors=analysis.contributing_factors,
            uncertainties=analysis.uncertainties,
            model=self._provider.model_name,
            prompt_version=PROMPT_VERSION,
            created_at=now,
            advisory_only=True,
        )

        # Persist the result
        await self._store.save_analysis(
            mission_id, incident_id, result
        )

        logger.info(
            "Analysis complete for incident '%s': root_cause='%s', "
            "confidence=%.2f",
            incident_id,
            result.root_cause,
            result.confidence,
        )

        return result

    async def get_analysis(
        self,
        mission_id: str,
        incident_id: str,
    ) -> Optional[ReasoningResult]:
        """Get the current persisted analysis for an incident."""
        return await self._store.get_analysis(mission_id, incident_id)

    async def list_analyses(
        self,
        mission_id: str,
    ) -> ReasoningListResponse:
        """List all persisted analyses for a mission."""
        analyses = await self._store.list_analyses(mission_id)
        return ReasoningListResponse(
            mission_id=mission_id,
            analyses=analyses,
            total=len(analyses),
        )
