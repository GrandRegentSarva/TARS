"""
Trace Attribute Names
=====================
Stable TARS-specific and OpenInference attribute constants for Phase 6
tracing spans.

These attribute names form the trace contract consumed by:
- Phase 8 (Phoenix MCP self-introspection)
- Phase 9 (Evaluation Layer)
- Phase 10 (Learning Engine)

Attribute names must remain stable across versions. Renaming an attribute
is a breaking change for downstream consumers.

OpenInference semantic conventions are used for LLM-specific attributes.
TARS-specific attributes use the ``tars.`` prefix.
"""

from __future__ import annotations


# =============================================================================
# Span Names
# =============================================================================

SPAN_REASONING_ANALYZE = "reasoning.analyze"
SPAN_REASONING_CACHE_LOOKUP = "reasoning.cache_lookup"
SPAN_PHASE4_GET_INCIDENT = "phase4.get_incident"
SPAN_REASONING_BUILD_PROMPT = "reasoning.build_prompt"
SPAN_GEMINI_GENERATE = "gemini.generate"
SPAN_REASONING_VALIDATE = "reasoning.validate"
SPAN_REASONING_PERSIST = "reasoning.persist"


# =============================================================================
# TARS Mission & Incident Attributes
# =============================================================================

TARS_MISSION_ID = "tars.mission.id"
TARS_INCIDENT_ID = "tars.incident.id"
TARS_INCIDENT_TYPE = "tars.incident.type"
TARS_INCIDENT_SEVERITY = "tars.incident.severity"


# =============================================================================
# TARS Reasoning Attributes
# =============================================================================

TARS_REASONING_ID = "tars.reasoning.id"
TARS_REASONING_CACHED = "tars.reasoning.cached"
TARS_REASONING_OVERWRITE = "tars.reasoning.overwrite"
TARS_REASONING_PROMPT_VERSION = "tars.reasoning.prompt_version"
TARS_REASONING_ROOT_CAUSE = "tars.reasoning.root_cause"
TARS_REASONING_CONFIDENCE = "tars.reasoning.confidence"
TARS_REASONING_ADVISORY_ONLY = "tars.reasoning.advisory_only"
TARS_REASONING_OUTCOME = "tars.reasoning.outcome"


# =============================================================================
# Reasoning Outcome Values
# =============================================================================

OUTCOME_SUCCESS = "success"
OUTCOME_CACHED = "cached"
OUTCOME_FAILED = "failed"


# =============================================================================
# OpenInference LLM Semantic Conventions
# =============================================================================
# See: https://github.com/Arize-ai/openinference/blob/main/spec/semantic_conventions.md

# LLM model attributes
OI_LLM_MODEL_NAME = "llm.model_name"
OI_LLM_PROVIDER = "llm.provider"
OI_LLM_INVOCATION_PARAMETERS = "llm.invocation_parameters"

# LLM input/output
OI_INPUT_VALUE = "input.value"
OI_INPUT_MIME_TYPE = "input.mime_type"
OI_OUTPUT_VALUE = "output.value"
OI_OUTPUT_MIME_TYPE = "output.mime_type"

# Token usage
OI_LLM_TOKEN_COUNT_PROMPT = "llm.token_count.prompt"
OI_LLM_TOKEN_COUNT_COMPLETION = "llm.token_count.completion"
OI_LLM_TOKEN_COUNT_TOTAL = "llm.token_count.total"

# OpenInference span kind
OI_OPENINFERENCE_SPAN_KIND = "openinference.span.kind"

# Span kind values
OI_SPAN_KIND_LLM = "LLM"
OI_SPAN_KIND_CHAIN = "CHAIN"
OI_SPAN_KIND_RETRIEVER = "RETRIEVER"
OI_SPAN_KIND_TOOL = "TOOL"


# =============================================================================
# Helpers
# =============================================================================

def reasoning_attributes(
    *,
    mission_id: str,
    incident_id: str,
    overwrite: bool,
) -> dict[str, str | bool]:
    """
    Build the initial attribute dict for a reasoning.analyze root span.

    These attributes are set at span creation. Additional attributes
    (reasoning_id, root_cause, confidence, outcome) are added after
    the reasoning completes.
    """
    return {
        TARS_MISSION_ID: mission_id,
        TARS_INCIDENT_ID: incident_id,
        TARS_REASONING_OVERWRITE: overwrite,
        TARS_REASONING_ADVISORY_ONLY: True,
        OI_OPENINFERENCE_SPAN_KIND: OI_SPAN_KIND_CHAIN,
    }


def incident_attributes(
    *,
    incident_type: str,
    severity: str,
) -> dict[str, str]:
    """
    Build incident-detail attributes added after Phase 4 retrieval.
    """
    return {
        TARS_INCIDENT_TYPE: incident_type,
        TARS_INCIDENT_SEVERITY: severity,
    }


def result_attributes(
    *,
    reasoning_id: str,
    root_cause: str,
    confidence: float,
    prompt_version: str,
    cached: bool = False,
) -> dict[str, str | float | bool]:
    """
    Build result attributes added after successful reasoning.
    """
    return {
        TARS_REASONING_ID: reasoning_id,
        TARS_REASONING_ROOT_CAUSE: root_cause,
        TARS_REASONING_CONFIDENCE: confidence,
        TARS_REASONING_PROMPT_VERSION: prompt_version,
        TARS_REASONING_CACHED: cached,
        TARS_REASONING_OUTCOME: OUTCOME_CACHED if cached else OUTCOME_SUCCESS,
    }


def gemini_attributes(
    *,
    model_name: str,
    prompt_version: str,
    provider: str = "google",
) -> dict[str, str]:
    """
    Build OpenInference LLM attributes for the Gemini span.
    """
    return {
        OI_LLM_MODEL_NAME: model_name,
        OI_LLM_PROVIDER: provider,
        TARS_REASONING_PROMPT_VERSION: prompt_version,
        OI_OPENINFERENCE_SPAN_KIND: OI_SPAN_KIND_LLM,
    }
