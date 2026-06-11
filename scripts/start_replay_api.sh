#!/usr/bin/env bash
# =============================================================================
# TARS Phase 2 -- Start Mission Replay API
# =============================================================================
# Usage:
#   ./scripts/start_replay_api.sh
#
# Prerequisites:
#   1. PostgreSQL running: docker compose -f docker/docker-compose.yml up postgres -d
#   2. Migrations applied: PYTHONPATH=src .venv/bin/alembic upgrade head
#   3. Virtual env with dependencies: pip install -r requirements.txt
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

# Load .env if it exists
if [ -f .env ]; then
    set -a
    source .env
    set +a
fi

API_HOST="${API_HOST:-0.0.0.0}"
API_PORT="${API_PORT:-8000}"

echo "============================================================"
echo "TARS Phase 2 -- Mission Replay API"
echo "============================================================"
echo "  Host:     $API_HOST"
echo "  Port:     $API_PORT"
echo "  Docs:     http://localhost:$API_PORT/docs"
echo "  Health:   http://localhost:$API_PORT/health"
echo "============================================================"

PYTHONPATH=src exec .venv/bin/uvicorn \
    tars.phase2.api:app \
    --host "$API_HOST" \
    --port "$API_PORT" \
    --reload
