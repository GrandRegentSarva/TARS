#!/usr/bin/env bash
# Start the Phase 7 Operational Memory API server.
#
# Usage:
#   ./scripts/start_memory_api.sh
#
# Requires:
#   - Neo4j running (docker compose -f docker/docker-compose.yml up neo4j -d)
#   - Python venv activated with dependencies installed
#   - NEO4J_PASSWORD set if Neo4j requires authentication

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

HOST="${MEMORY_API_HOST:-0.0.0.0}"
PORT="${MEMORY_API_PORT:-8005}"

echo "Starting Phase 7 Operational Memory API on ${HOST}:${PORT}..."
echo "Neo4j: ${NEO4J_URI:-bolt://localhost:7687}"
echo "Phase 2 API: ${PHASE2_API_URL:-http://localhost:8000}"
echo "Phase 4 API: ${PHASE4_API_URL:-http://localhost:8003}"
echo "Phase 5 API: ${PHASE5_API_URL:-http://localhost:8004}"

PYTHONPATH=src exec .venv/bin/uvicorn \
    tars.phase7.api:app \
    --host "$HOST" \
    --port "$PORT"
