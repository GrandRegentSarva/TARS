"""
Google ADK Gemini Agent
========================
Single-purpose incident-analysis agent backed by Gemini via Google ADK.

The agent is deliberately narrow:
- One incident per invocation.
- No tools that can control the drone or mutate upstream data.
- Structured response schema enforced via Agent.output_schema.
- Low temperature for stable operational reasoning.
- Versioned system instruction.
- Explicit instruction to avoid inventing telemetry.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from google.adk.agents import Agent
from google.genai import types as genai_types

from .config import settings
from .prompts import SYSTEM_INSTRUCTION

logger = logging.getLogger("phase5.agent")

# ============================================================================
# Response Schema
# ============================================================================

REASONING_RESPONSE_SCHEMA = genai_types.Schema(
    type=genai_types.Type.OBJECT,
    properties={
        "root_cause": genai_types.Schema(
            type=genai_types.Type.STRING,
            description="Most likely concise cause classification.",
        ),
        "confidence": genai_types.Schema(
            type=genai_types.Type.NUMBER,
            description="Model confidence from 0.0 to 1.0.",
        ),
        "recommendation": genai_types.Schema(
            type=genai_types.Type.STRING,
            description="Advisory operational recommendation.",
        ),
        "rationale": genai_types.Schema(
            type=genai_types.Type.STRING,
            description="Short explanation grounded in incident evidence.",
        ),
        "contributing_factors": genai_types.Schema(
            type=genai_types.Type.ARRAY,
            items=genai_types.Schema(type=genai_types.Type.STRING),
            description="Evidence-backed supporting factors.",
        ),
        "uncertainties": genai_types.Schema(
            type=genai_types.Type.ARRAY,
            items=genai_types.Schema(type=genai_types.Type.STRING),
            description="Missing information or plausible alternatives.",
        ),
    },
    required=[
        "root_cause",
        "confidence",
        "recommendation",
        "rationale",
        "contributing_factors",
        "uncertainties",
    ],
)


# ============================================================================
# Agent Factory
# ============================================================================

def create_reasoning_agent() -> Agent:
    """
    Create a Google ADK agent configured for incident reasoning.

    The response schema is set via output_schema (ADK 2.2.0+),
    not inside generate_content_config.

    Returns:
        Configured Agent instance.
    """
    agent = Agent(
        name="tars_incident_analyst",
        model=settings.GEMINI_MODEL,
        description=(
            "Advisory incident analyst for autonomous drone missions. "
            "Analyzes Phase 4 incidents and produces structured root-cause "
            "assessments. Never issues flight commands."
        ),
        instruction=SYSTEM_INSTRUCTION,
        output_schema=REASONING_RESPONSE_SCHEMA,
        generate_content_config=genai_types.GenerateContentConfig(
            temperature=settings.GEMINI_TEMPERATURE,
            response_mime_type="application/json",
        ),
    )

    return agent
