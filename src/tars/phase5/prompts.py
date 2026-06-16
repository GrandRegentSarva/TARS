"""
Reasoning Prompts
=================
Versioned system instruction and incident prompt for Gemini reasoning.

Prompt design principles:
1. The model is an advisory incident analyst.
2. Phase 4 incident data is the complete evidence available.
3. Conclusions must be grounded in supplied evidence.
4. Ambiguity must be represented through confidence and uncertainties.
5. Recommendations must not claim execution or issue actuator commands.
6. Output must conform to the structured response schema.
"""

from __future__ import annotations

import json
from typing import Any, Optional

# Current prompt version -- increment when prompt content changes
PROMPT_VERSION = "1.0.0"

# ============================================================================
# System Instruction
# ============================================================================

SYSTEM_INSTRUCTION = """\
You are an advisory incident analyst for autonomous drone missions.

Your role:
- Analyze bounded operational incidents detected by the Phase 4 Incident Engine.
- Produce structured root-cause assessments grounded in the supplied evidence.
- Provide advisory recommendations only. You must NEVER issue flight commands, \
actuator commands, or any instruction that could directly control a drone.

Rules:
1. The Phase 4 incident data provided is the COMPLETE evidence available to you. \
Do not invent telemetry, sensor readings, or data not present in the incident.
2. Your conclusions must be traceable to the supplied evidence fields: \
incident_type, severity, start_ms, end_ms, contributing_states, peak_risk, \
phases, and evidence list.
3. When evidence is ambiguous or incomplete, you MUST:
   - Lower your confidence score.
   - List the ambiguity or missing information in the uncertainties field.
4. Your recommendation must be advisory only. Use phrases like "consider", \
"evaluate", "investigate", "review". Never use "execute", "send_command", \
"arm", "disarm", "takeoff", "land", "set_mode", or similar control verbs.
5. Contributing factors must reference specific evidence from the incident.
6. If you cannot determine a root cause with reasonable confidence, say so \
honestly and set confidence below 0.5.

Output format:
You must respond with a JSON object containing exactly these fields:
- root_cause: string (concise cause classification)
- confidence: number (0.0 to 1.0)
- recommendation: string (advisory only)
- rationale: string (grounded in evidence)
- contributing_factors: array of strings (evidence-backed)
- uncertainties: array of strings (missing info or alternatives)

Do not include any text outside the JSON object.
"""


# ============================================================================
# Incident Prompt Builder
# ============================================================================

def build_incident_prompt(
    incident: dict[str, Any],
    introspection_context: Optional[Any] = None,
) -> str:
    """
    Build the incident analysis prompt from a bounded Phase 4 incident.

    Only includes the fields relevant to reasoning:
    - incident_type, severity
    - start_ms, end_ms
    - contributing_states, peak_risk
    - phases
    - evidence (deduplicated)

    When introspection_context is provided (Phase 8), appends bounded
    prior trace summaries with explicit limitations.

    Args:
        incident: Phase 4 incident dict.
        introspection_context: Optional Phase 8 IntrospectionContext.

    Returns:
        Formatted prompt string with incident JSON and task instruction.
    """
    # Extract only the bounded incident contract fields
    bounded = {
        "incident_type": incident.get("incident_type", "unknown"),
        "severity": incident.get("severity", "unknown"),
        "start_ms": incident.get("start_ms", 0),
        "end_ms": incident.get("end_ms", 0),
        "contributing_states": incident.get("contributing_states", 0),
        "peak_risk": incident.get("peak_risk", 0.0),
        "phases": incident.get("phases", []),
        "evidence": incident.get("evidence", []),
    }

    incident_json = json.dumps(bounded, indent=2)

    # Build introspection section if available
    introspection_section = ""
    if introspection_context is not None:
        introspection_section = _build_introspection_section(
            introspection_context
        )

    return f"""\
Prompt version: {PROMPT_VERSION}

Analyze the following Phase 4 incident and produce a structured root-cause \
assessment.

Incident data:
```json
{incident_json}
```
{introspection_section}
Task:
1. Identify the most likely root cause based on the incident type, severity, \
timing, risk level, and evidence.
2. Assess your confidence (0.0-1.0) based on evidence completeness.
3. Provide an advisory recommendation (never a flight command).
4. Explain your rationale grounded in the supplied evidence.
5. List contributing factors traceable to the evidence.
6. List any uncertainties or missing information.

Respond with a single JSON object matching the required schema."""


def _build_introspection_section(context: Any) -> str:
    """
    Build the introspection section for the reasoning prompt.

    Explicitly states that trace history is descriptive, not validated
    ground truth, and must not be treated as evaluation.

    Args:
        context: Phase 8 IntrospectionContext object.

    Returns:
        Formatted introspection section string.
    """
    lines = [
        "",
        "Prior reasoning trace context (descriptive only, NOT ground truth):",
        "WARNING: The following trace history is descriptive and has NOT been "
        "validated. Do NOT treat trace frequency as correctness. Use this "
        "context only as additional evidence to consider, not as validation.",
        "",
    ]

    # Add trace IDs consulted
    trace_ids = getattr(context, "traces_consulted", [])
    if trace_ids:
        lines.append(f"Traces consulted: {', '.join(trace_ids[:5])}")

    # Add summary statements
    summaries = getattr(context, "summary", [])
    for s in summaries[:5]:
        lines.append(f"- {s}")

    # Add limitations
    limitations = getattr(context, "limitations", [])
    if limitations:
        lines.append("")
        lines.append("Limitations:")
        for lim in limitations:
            lines.append(f"- {lim}")

    lines.append("")
    return "\n".join(lines)
