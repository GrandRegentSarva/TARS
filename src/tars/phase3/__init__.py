"""
Phase 3 -- State Engine
=======================
Transforms raw telemetry replay frames into operational state snapshots.

Consumes Phase 2 replay frames and produces deterministic state including:
- Mission phase classification (preflight, takeoff, climb, cruise, etc.)
- Health assessment (nominal, degraded, critical)
- Risk scoring (0.0 to 1.0)
- Signal quality indicators
- Human-readable reason strings

State is stored in Redis for low-latency access by downstream phases.
"""
