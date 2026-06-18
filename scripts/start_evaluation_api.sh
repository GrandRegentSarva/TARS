#!/usr/bin/env bash
# =============================================================================
# Start Phase 9 Evaluation API
# =============================================================================
# Usage:
#   ./scripts/start_evaluation_api.sh
#
# Prerequisites:
#   - PostgreSQL running with evaluation tables migrated
#   - pip install -r requirements.txt
#
# Environment variables (see .env.example for full list):
#   EVALUATION_DATABASE_URL  PostgreSQL connection string
#   EVALUATION_API_HOST      API bind host (default: 0.0.0.0)
#   EVALUATION_API_PORT      API bind port (default: 8006)
#   EVALUATION_ENABLED       Enable evaluation (default: true)
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

HOST="${EVALUATION_API_HOST:-0.0.0.0}"
PORT="${EVALUATION_API_PORT:-8006}"

echo "Starting Phase 9 Evaluation API on ${HOST}:${PORT}"
echo "Database: ${EVALUATION_DATABASE_URL:-postgresql+asyncpg://tars:tars@localhost:5432/tars}"
echo "Evaluator version: ${EVALUATION_VERSION:-v1.0}"

PYTHONPATH=src exec uvicorn tars.phase9.api:app \
    --host "$HOST" \
    --port "$PORT" \
    --log-level info
