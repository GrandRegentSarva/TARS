"""
Phase 8 -- Phoenix MCP Self-Introspection
==========================================
Provides analysis-only trace introspection tools that let the reasoning
agent inspect its own prior reasoning traces through Phoenix.

Phase 8 answers "Why did I reason this way before?" It does not score,
learn from, or automatically change recommendations.

Components:
- config: Phoenix MCP settings, limits, timeout, and content mode.
- models: Tool inputs, safe trace summaries, and introspection metadata.
- phoenix_client: Phoenix trace query client.
- summarizer: Raw trace-to-safe-summary conversion.
- mcp_tools: MCP tool registration and schemas.
- service: Orchestration for trace search and comparison.
- tool_policy: Rules for when Phase 5 may call introspection.
"""

from __future__ import annotations
