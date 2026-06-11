#!/usr/bin/env bash
# =============================================================================
# Start Phase 3 State Engine API
# =============================================================================
# Usage:
#   ./scripts/start_state_api.sh
#
# Prerequisites:
#   - Redis running (docker compose up redis)
#   - Phase 2 API running on port 8000 (for replay data)
#   - Python venv with requirements installed
#
# Environment variables (see .env.example):
#   REDIS_URL          - Redis connection URL (default: redis://localhost:6379/0)
#   PHASE2_API_URL     - Phase 2 API base URL (default: http://localhost:8000)
#   STATE_API_HOST     - API bind host (default: 0.0.0.0)
#   STATE_API_PORT     - API bind port (default: 8002)
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

# Load .env if present
if [ -f .env ]; then
    set -a
    source .env
    set +a
fi

HOST="${STATE_API_HOST:-0.0.0.0}"
PORT="${STATE_API_PORT:-8002}"

echo "=== TARS Phase 3 -- State Engine API ==="
echo "Redis:      ${REDIS_URL:-redis://localhost:6379/0}"
echo "Phase 2:    ${PHASE2_API_URL:-http://localhost:8000}"
echo "Listening:  http://${HOST}:${PORT}"
echo "========================================="

PYTHONPATH=src exec .venv/bin/uvicorn tars.phase3.api:app \
    --host "$HOST" \
    --port "$PORT"
