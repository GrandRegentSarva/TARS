"""
Reasoning Providers
====================
Production Gemini provider and deterministic fake provider for tests.

The provider boundary enforces structured output validation before
any result is returned to the service layer.

Phase 6 tracing:
The provider creates a ``gemini.generate`` child span under the current
trace context. It captures model name, prompt version, bounded prompt
(in full content mode), structured response, and token usage when
available. Tracing is best-effort and never changes return values or
exception behavior.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from google.adk.agents import Agent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types as genai_types

from opentelemetry import trace
from opentelemetry.trace import StatusCode

from .config import settings
from .models import ReasoningAnalysis
from .prompts import PROMPT_VERSION, build_incident_prompt

logger = logging.getLogger("phase5.provider")


def _get_tracer() -> trace.Tracer:
    """Get the Phase 6 tracer, falling back to no-op if unavailable."""
    try:
        from tars.phase6.tracing import get_tracer
        return get_tracer()
    except ImportError:
        return trace.get_tracer("tars.phase5")


def _get_attributes():
    """Import Phase 6 attributes, returning None if unavailable."""
    try:
        from tars.phase6 import attributes as attrs
        return attrs
    except ImportError:
        return None


def _get_config():
    """Import Phase 6 config, returning None if unavailable."""
    try:
        from tars.phase6.config import phoenix_settings
        return phoenix_settings
    except ImportError:
        return None


# ============================================================================
# Production Gemini Provider (via Google ADK)
# ============================================================================

class GeminiReasoningProvider:
    """
    Production reasoning provider using Google ADK and Gemini.

    Invokes the ADK agent with a bounded incident prompt and
    validates the structured JSON response.
    """

    def __init__(self, agent: Agent) -> None:
        self._agent = agent
        self._session_service = InMemorySessionService()

    @property
    def model_name(self) -> str:
        """Return the Gemini model identifier."""
        return settings.GEMINI_MODEL

    def is_configured(self) -> bool:
        """Return True if a Gemini API key is set."""
        return bool(settings.GEMINI_API_KEY)

    async def analyze(self, incident: dict[str, Any]) -> ReasoningAnalysis:
        """
        Produce a root-cause analysis for a single Phase 4 incident.

        Args:
            incident: Bounded Phase 4 incident dict.

        Returns:
            Validated ReasoningAnalysis.

        Raises:
            RuntimeError: If the provider is not configured.
            ValueError: If the model output is malformed.
        """
        if not self.is_configured():
            raise RuntimeError(
                "Gemini provider is not configured. "
                "Set GEMINI_API_KEY environment variable."
            )

        tracer = _get_tracer()
        attrs = _get_attributes()
        cfg = _get_config()

        # Build span attributes
        span_attrs = {}
        if attrs is not None:
            span_attrs = attrs.gemini_attributes(
                model_name=self.model_name,
                prompt_version=PROMPT_VERSION,
            )

        span_name = (
            attrs.SPAN_GEMINI_GENERATE
            if attrs is not None
            else "gemini.generate"
        )

        with tracer.start_as_current_span(
            span_name,
            attributes=span_attrs,
        ) as gemini_span:
            try:
                return await self._invoke_gemini(
                    incident=incident,
                    gemini_span=gemini_span,
                    attrs=attrs,
                    cfg=cfg,
                )
            except Exception as exc:
                gemini_span.set_status(StatusCode.ERROR, str(exc))
                gemini_span.record_exception(exc)
                raise

    async def _invoke_gemini(
        self,
        *,
        incident: dict[str, Any],
        gemini_span: trace.Span,
        attrs: Any,
        cfg: Any,
    ) -> ReasoningAnalysis:
        """
        Internal Gemini invocation with tracing instrumentation.
        """
        prompt = build_incident_prompt(incident)

        # Capture bounded prompt in full content mode
        capture_content = cfg is not None and cfg.capture_content
        if capture_content and attrs is not None:
            gemini_span.set_attribute(attrs.OI_INPUT_VALUE, prompt)
            gemini_span.set_attribute(attrs.OI_INPUT_MIME_TYPE, "text/plain")

        # Create a unique session for this analysis.
        # Each session is deleted after use to prevent memory accumulation.
        incident_id = incident.get("incident_id", "unknown")
        user_id = "phase5_reasoning"
        session = await self._session_service.create_session(
            app_name="tars_incident_analyst",
            user_id=user_id,
        )

        runner = Runner(
            agent=self._agent,
            app_name="tars_incident_analyst",
            session_service=self._session_service,
        )

        # Send the prompt and collect the response
        user_content = genai_types.Content(
            role="user",
            parts=[genai_types.Part.from_text(text=prompt)],
        )

        try:
            response_text = ""
            async for event in runner.run_async(
                user_id=session.user_id,
                session_id=session.id,
                new_message=user_content,
            ):
                if event.is_final_response():
                    if (
                        event.content
                        and event.content.parts
                    ):
                        response_text = event.content.parts[0].text or ""
        finally:
            # Clean up the session to prevent memory accumulation
            try:
                await self._session_service.delete_session(
                    app_name="tars_incident_analyst",
                    user_id=user_id,
                    session_id=session.id,
                )
            except Exception as cleanup_exc:
                logger.debug(
                    "Session cleanup failed for incident '%s': %s",
                    incident_id,
                    cleanup_exc,
                )

        if not response_text:
            raise ValueError("Gemini returned an empty response")

        logger.debug(
            "Gemini raw response for incident '%s': %s",
            incident_id,
            response_text[:500],
        )

        # Capture structured response in full content mode
        if capture_content and attrs is not None:
            gemini_span.set_attribute(
                attrs.OI_OUTPUT_VALUE, response_text
            )
            gemini_span.set_attribute(
                attrs.OI_OUTPUT_MIME_TYPE, "application/json"
            )

        # Parse and validate the structured output
        try:
            raw = json.loads(response_text)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"Gemini response is not valid JSON: {exc}"
            ) from exc

        # Validate through Pydantic model
        analysis = ReasoningAnalysis.model_validate(raw)
        return analysis


# ============================================================================
# Deterministic Fake Provider (for tests)
# ============================================================================

class FakeReasoningProvider:
    """
    Deterministic fake provider for testing.

    Returns predictable analysis results based on incident type
    without requiring Gemini credentials or network calls.

    Phase 6 tracing: Creates a ``gemini.generate`` span just like
    the production provider, so trace tests can verify the full
    span hierarchy.
    """

    def __init__(
        self,
        *,
        model_name: str = "fake-gemini-test",
        configured: bool = True,
        fail: bool = False,
        fail_message: str = "Fake provider failure",
        custom_response: ReasoningAnalysis | None = None,
    ) -> None:
        self._model_name = model_name
        self._configured = configured
        self._fail = fail
        self._fail_message = fail_message
        self._custom_response = custom_response
        self._call_count = 0
        self._last_incident: dict[str, Any] | None = None

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def call_count(self) -> int:
        """Number of times analyze() has been called."""
        return self._call_count

    @property
    def last_incident(self) -> dict[str, Any] | None:
        """The last incident passed to analyze()."""
        return self._last_incident

    def is_configured(self) -> bool:
        return self._configured

    async def analyze(self, incident: dict[str, Any]) -> ReasoningAnalysis:
        self._call_count += 1
        self._last_incident = incident

        tracer = _get_tracer()
        attrs = _get_attributes()
        cfg = _get_config()

        # Build span attributes
        span_attrs = {}
        if attrs is not None:
            span_attrs = attrs.gemini_attributes(
                model_name=self._model_name,
                prompt_version=PROMPT_VERSION,
            )

        span_name = (
            attrs.SPAN_GEMINI_GENERATE
            if attrs is not None
            else "gemini.generate"
        )

        with tracer.start_as_current_span(
            span_name,
            attributes=span_attrs,
        ) as gemini_span:
            if not self._configured:
                exc = RuntimeError("Fake provider is not configured")
                gemini_span.set_status(StatusCode.ERROR, str(exc))
                gemini_span.record_exception(exc)
                raise exc

            if self._fail:
                exc = ValueError(self._fail_message)
                gemini_span.set_status(StatusCode.ERROR, str(exc))
                gemini_span.record_exception(exc)
                raise exc

            if self._custom_response is not None:
                # Capture content in full mode
                capture_content = cfg is not None and cfg.capture_content
                if capture_content and attrs is not None:
                    prompt = build_incident_prompt(incident)
                    gemini_span.set_attribute(attrs.OI_INPUT_VALUE, prompt)
                    gemini_span.set_attribute(
                        attrs.OI_INPUT_MIME_TYPE, "text/plain"
                    )
                    gemini_span.set_attribute(
                        attrs.OI_OUTPUT_VALUE,
                        self._custom_response.model_dump_json(),
                    )
                    gemini_span.set_attribute(
                        attrs.OI_OUTPUT_MIME_TYPE, "application/json"
                    )
                return self._custom_response

            # Generate deterministic response based on incident type
            incident_type = incident.get("incident_type", "unknown")
            severity = incident.get("severity", "unknown")
            evidence = incident.get("evidence", [])
            peak_risk = incident.get("peak_risk", 0.0)

            # Map incident types to root causes
            root_cause_map = {
                "navigation_instability": "gps_interference",
                "battery_degradation": "accelerated_discharge",
                "attitude_instability": "imu_calibration_drift",
                "altitude_instability": "barometric_pressure_change",
                "sensor_health_failure": "sensor_hardware_fault",
                "telemetry_degradation": "communication_link_quality",
                "high_risk_state": "compound_system_stress",
            }

            root_cause = root_cause_map.get(incident_type, "undetermined")

            # Confidence based on evidence count and peak risk
            base_confidence = min(0.5 + len(evidence) * 0.1, 0.95)
            confidence = round(
                min(base_confidence + peak_risk * 0.1, 0.99), 2
            )

            # Recommendation map
            recommendation_map = {
                "navigation_instability": (
                    "consider switching to visual navigation or "
                    "investigating GPS interference sources"
                ),
                "battery_degradation": (
                    "consider reducing mission duration or "
                    "evaluating battery health before next flight"
                ),
                "attitude_instability": (
                    "consider recalibrating IMU sensors and "
                    "reviewing flight controller tuning"
                ),
                "altitude_instability": (
                    "consider cross-referencing altitude sources and "
                    "evaluating barometric sensor placement"
                ),
                "sensor_health_failure": (
                    "consider pre-flight sensor diagnostics and "
                    "reviewing hardware maintenance schedule"
                ),
                "telemetry_degradation": (
                    "consider evaluating communication link quality and "
                    "reviewing antenna placement"
                ),
                "high_risk_state": (
                    "consider reviewing compound risk factors and "
                    "evaluating mission abort criteria"
                ),
            }

            recommendation = recommendation_map.get(
                incident_type,
                "consider investigating the incident further",
            )

            # Build rationale from evidence
            if evidence:
                rationale = (
                    f"Analysis of {incident_type} incident with "
                    f"{severity} severity. {evidence[0]}."
                )
            else:
                rationale = (
                    f"Analysis of {incident_type} incident with "
                    f"{severity} severity. Limited evidence available."
                )

            # Contributing factors from evidence
            contributing_factors = [
                f"{e} (observed during incident)" for e in evidence[:3]
            ]
            if peak_risk >= 0.7:
                contributing_factors.append("elevated mission risk level")

            # Uncertainties
            uncertainties = []
            if len(evidence) < 2:
                uncertainties.append(
                    "Limited evidence available for comprehensive analysis"
                )
            if peak_risk < 0.5:
                uncertainties.append(
                    "Moderate risk level may indicate intermittent condition"
                )
            uncertainties.append(
                "No environmental interference measurement is available"
            )

            analysis = ReasoningAnalysis(
                root_cause=root_cause,
                confidence=confidence,
                recommendation=recommendation,
                rationale=rationale,
                contributing_factors=contributing_factors,
                uncertainties=uncertainties,
            )

            # Capture content in full mode
            capture_content = cfg is not None and cfg.capture_content
            if capture_content and attrs is not None:
                prompt = build_incident_prompt(incident)
                gemini_span.set_attribute(attrs.OI_INPUT_VALUE, prompt)
                gemini_span.set_attribute(
                    attrs.OI_INPUT_MIME_TYPE, "text/plain"
                )
                gemini_span.set_attribute(
                    attrs.OI_OUTPUT_VALUE,
                    analysis.model_dump_json(),
                )
                gemini_span.set_attribute(
                    attrs.OI_OUTPUT_MIME_TYPE, "application/json"
                )

            return analysis
