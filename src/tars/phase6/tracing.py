"""
Tracing Bootstrap
=================
Configures OpenTelemetry, the OTLP exporter, and provides the tracer
used by Phase 5 instrumentation.

Design principles:
- Tracing is best-effort and fails open.
- A Phoenix outage never blocks reasoning.
- Disabled tracing returns no-op behavior.
- Repeated initialization is safe (idempotent).
- Shutdown flushes pending spans within a timeout.

Usage::

    from tars.phase6.tracing import init_tracing, shutdown_tracing, get_tracer

    # At API startup
    init_tracing()

    # Get a tracer for instrumentation
    tracer = get_tracer()

    # At API shutdown
    shutdown_tracing()
"""

from __future__ import annotations

import logging
from typing import Optional

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    SimpleSpanProcessor,
    SpanExporter,
)

from .config import ContentMode, PhoenixSettings, phoenix_settings

logger = logging.getLogger("phase6.tracing")

# Module-level state
_tracer_provider: Optional[TracerProvider] = None
_initialized: bool = False


def init_tracing(
    settings: Optional[PhoenixSettings] = None,
    exporter: Optional[SpanExporter] = None,
) -> trace.Tracer:
    """
    Initialize OpenTelemetry tracing for Phase 5 reasoning observability.

    When tracing is disabled, returns a no-op tracer. When enabled,
    configures a TracerProvider with an OTLP HTTP exporter targeting
    Phoenix.

    Args:
        settings: Optional settings override (for testing).
        exporter: Optional exporter override (for in-memory test exporter).

    Returns:
        A configured or no-op Tracer instance.
    """
    global _tracer_provider, _initialized

    cfg = settings or phoenix_settings

    # If tracing is disabled, return no-op
    if not cfg.is_tracing_enabled:
        logger.info(
            "Phoenix tracing disabled (PHOENIX_ENABLED=%s, "
            "PHOENIX_CONTENT_MODE=%s)",
            cfg.ENABLED,
            cfg.CONTENT_MODE.value,
        )
        _initialized = True
        return trace.get_tracer("tars.phase6", tracer_provider=trace.NoOpTracerProvider())

    # Prevent double initialization
    if _initialized and _tracer_provider is not None and exporter is None:
        logger.debug("Tracing already initialized; returning existing tracer")
        return _tracer_provider.get_tracer("tars.phase6")

    try:
        # Build resource with Phoenix project name
        resource = Resource.create(
            {
                "service.name": "tars-reasoning",
                "project.name": cfg.PROJECT_NAME,
            }
        )

        _tracer_provider = TracerProvider(resource=resource)

        # Use provided exporter or create OTLP HTTP exporter
        if exporter is not None:
            span_exporter = exporter
        else:
            span_exporter = _create_otlp_exporter(cfg)

        # Add span processor
        # SimpleSpanProcessor is only used when a test exporter is injected.
        # Production always uses BatchSpanProcessor to avoid blocking
        # reasoning requests on slow or unreachable Phoenix exports.
        if exporter is not None:
            # Test path: SimpleSpanProcessor for deterministic span capture
            processor = SimpleSpanProcessor(span_exporter)
        else:
            # Production path: always batch to satisfy fail-open requirement
            processor = BatchSpanProcessor(
                span_exporter,
                export_timeout_millis=int(cfg.EXPORT_TIMEOUT_SECONDS * 1000),
            )

        _tracer_provider.add_span_processor(processor)

        # Set as global provider
        trace.set_tracer_provider(_tracer_provider)

        _initialized = True
        logger.info(
            "Phoenix tracing initialized: endpoint=%s, project=%s, "
            "content_mode=%s, batch=%s",
            cfg.ENDPOINT,
            cfg.PROJECT_NAME,
            cfg.CONTENT_MODE.value,
            cfg.BATCH_EXPORT,
        )

        return _tracer_provider.get_tracer("tars.phase6")

    except Exception as exc:
        logger.warning(
            "Failed to initialize Phoenix tracing: %s. "
            "Reasoning will continue without tracing.",
            exc,
        )
        _initialized = True
        return trace.get_tracer("tars.phase6", tracer_provider=trace.NoOpTracerProvider())


def _create_otlp_exporter(cfg: PhoenixSettings) -> SpanExporter:
    """
    Create an OTLP HTTP span exporter targeting Phoenix.

    Raises on import failure if opentelemetry-exporter-otlp-proto-http
    is not installed.
    """
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
        OTLPSpanExporter,
    )

    return OTLPSpanExporter(
        endpoint=cfg.otlp_endpoint,
        timeout=int(cfg.EXPORT_TIMEOUT_SECONDS),
    )


def shutdown_tracing(timeout_ms: int = 5000) -> None:
    """
    Flush pending spans and shut down the tracer provider.

    Safe to call even if tracing was never initialized or is disabled.

    Args:
        timeout_ms: Maximum time to wait for pending spans to flush.
    """
    global _tracer_provider, _initialized

    if _tracer_provider is not None:
        try:
            _tracer_provider.force_flush(timeout_millis=timeout_ms)
            _tracer_provider.shutdown()
            logger.info("Phoenix tracing shut down successfully")
        except Exception as exc:
            logger.warning(
                "Phoenix tracing shutdown warning: %s", exc
            )
        finally:
            _tracer_provider = None
            _initialized = False
    else:
        logger.debug("No tracer provider to shut down")
        _initialized = False


def get_tracer() -> trace.Tracer:
    """
    Return the current tracer.

    If tracing has not been initialized, returns a no-op tracer.
    This ensures instrumentation code never needs to check for None.
    """
    if _tracer_provider is not None:
        return _tracer_provider.get_tracer("tars.phase6")
    return trace.get_tracer("tars.phase6")


def is_tracing_active() -> bool:
    """
    Return True if tracing has been initialized with a real provider.

    Used by the health endpoint to report Phoenix status.
    """
    return _initialized and _tracer_provider is not None


def get_provider() -> Optional[TracerProvider]:
    """
    Return the current TracerProvider, or None if not initialized.

    Exposed for testing purposes only.
    """
    return _tracer_provider


def reset_tracing() -> None:
    """
    Reset tracing state completely. For testing only.

    Shuts down any existing provider and clears module state.
    """
    global _tracer_provider, _initialized

    if _tracer_provider is not None:
        try:
            _tracer_provider.shutdown()
        except Exception:
            pass

    _tracer_provider = None
    _initialized = False
