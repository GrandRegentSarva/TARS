#!/usr/bin/env bash
# =============================================================================
# TARS Phase 2 -- Import Mission JSON
# =============================================================================
# Usage:
#   ./scripts/import_mission.sh output/mission_20260608_120000.json
#   ./scripts/import_mission.sh output/mission_20260608_120000.json --overwrite
#
# Prerequisites:
#   1. PostgreSQL running: docker compose -f docker/docker-compose.yml up postgres -d
#   2. Migrations applied: PYTHONPATH=src .venv/bin/alembic upgrade head
#   3. Replay API running: ./scripts/start_replay_api.sh
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

API_PORT="${API_PORT:-8000}"
API_BASE="http://localhost:$API_PORT/api/v1"

# Check arguments
if [ $# -lt 1 ]; then
    echo "Usage: $0 <mission_json_path> [--overwrite]"
    echo ""
    echo "Examples:"
    echo "  $0 output/mission_20260608_120000.json"
    echo "  $0 output/mission_20260608_120000.json --overwrite"
    exit 1
fi

FILE_PATH="$1"
OVERWRITE="false"

if [ "${2:-}" = "--overwrite" ]; then
    OVERWRITE="true"
fi

echo "============================================================"
echo "TARS Phase 2 -- Import Mission"
echo "============================================================"
echo "  File:      $FILE_PATH"
echo "  Overwrite: $OVERWRITE"
echo "  API:       $API_BASE"
echo "============================================================"

# Import via the API
RESPONSE=$(curl -s -w "\n%{http_code}" -X POST \
    "$API_BASE/missions/import" \
    -H "Content-Type: application/json" \
    -d "{\"path\": \"$FILE_PATH\", \"overwrite\": $OVERWRITE}")

# Split response body and HTTP status code
HTTP_CODE=$(echo "$RESPONSE" | tail -1)
BODY=$(echo "$RESPONSE" | sed '$d')

echo ""
echo "HTTP $HTTP_CODE"
echo "$BODY" | python3 -m json.tool 2>/dev/null || echo "$BODY"
echo ""

if [ "$HTTP_CODE" = "200" ]; then
    echo "Import successful."
else
    echo "Import failed (HTTP $HTTP_CODE)."
    exit 1
fi
