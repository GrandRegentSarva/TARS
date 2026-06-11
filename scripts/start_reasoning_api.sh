#!/usr/bin/env bash
# Start the Phase 5 Gemini Reasoning API server.
#
# Usage:
#   ./scripts/start_reasoning_api.sh
#
# Requires:
#   - Redis running (docker compose -f docker/docker-compose.yml up redis -d)
#   - Phase 4 Incident API running (./scripts/start_incident_api.sh)
#   - Python venv activated with dependencies installed
#   - GEMINI_API_KEY set for live reasoning (optional for startup)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

HOST="${REASONING_API_HOST:-0.0.0.0}"
PORT="${REASONING_API_PORT:-8004}"

echo "Starting Phase 5 Gemini Reasoning API on ${HOST}:${PORT}..."
echo "Phase 4 API: ${PHASE4_API_URL:-http://localhost:8003}"
echo "Redis: ${REDIS_URL:-redis://localhost:6379/0}"
echo "Gemini model: ${GEMINI_MODEL:-gemini-2.5-flash}"

if [ -z "${GEMINI_API_KEY:-}" ]; then
    echo "WARNING: GEMINI_API_KEY not set. Analysis endpoints will return configuration errors."
fi

PYTHONPATH=src exec .venv/bin/uvicorn \
    tars.phase5.api:app \
    --host "$HOST" \
    --port "$PORT"
