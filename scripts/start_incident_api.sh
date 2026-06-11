#!/usr/bin/env bash
# Start the Phase 4 Incident Engine API server.
#
# Usage:
#   ./scripts/start_incident_api.sh
#
# Requires:
#   - Redis running (docker compose -f docker/docker-compose.yml up redis -d)
#   - Phase 3 State API running (./scripts/start_state_api.sh)
#   - Python venv activated with dependencies installed

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

HOST="${INCIDENT_API_HOST:-0.0.0.0}"
PORT="${INCIDENT_API_PORT:-8003}"

echo "Starting Phase 4 Incident Engine API on ${HOST}:${PORT}..."
echo "Phase 3 API: ${PHASE3_API_URL:-http://localhost:8002}"
echo "Redis: ${REDIS_URL:-redis://localhost:6379/0}"

PYTHONPATH=src exec .venv/bin/uvicorn \
    tars.phase4.api:app \
    --host "$HOST" \
    --port "$PORT"
