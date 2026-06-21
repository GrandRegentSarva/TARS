#!/usr/bin/env bash
# Start the Phase 10 Learning API
#
# Usage:
#   ./scripts/start_learning_api.sh
#
# Environment variables (see .env.example for full list):
#   LEARNING_DATABASE_URL   PostgreSQL connection string
#   LEARNING_API_HOST       Bind address (default: 0.0.0.0)
#   LEARNING_API_PORT       Port (default: 8007)
#   LEARNING_ENABLED        Enable/disable (default: true)
#   LEARNING_VERSION        Version stamp (default: phase10.v1)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

HOST="${LEARNING_API_HOST:-0.0.0.0}"
PORT="${LEARNING_API_PORT:-8007}"

echo "Starting Phase 10 Learning API on ${HOST}:${PORT}"
echo "Learning version: ${LEARNING_VERSION:-phase10.v1}"

PYTHONPATH=src exec uvicorn tars.phase10.api:app \
    --host "$HOST" \
    --port "$PORT" \
    --reload
