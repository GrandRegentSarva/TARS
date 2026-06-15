#!/usr/bin/env bash
# Sync a completed mission into the Phase 7 operational memory graph.
#
# Usage:
#   ./scripts/sync_mission_memory.sh <mission_id>
#   ./scripts/sync_mission_memory.sh <mission_id> --no-reasoning
#   ./scripts/sync_mission_memory.sh <mission_id> --require-reasoning
#
# Requires:
#   - Phase 7 Memory API running (./scripts/start_memory_api.sh)
#   - Phase 2, Phase 4 APIs running
#   - Phase 5 API running (optional, for reasoning)

set -euo pipefail

MEMORY_API="${MEMORY_API_URL:-http://localhost:8005}"

if [ $# -lt 1 ]; then
    echo "Usage: $0 <mission_id> [--no-reasoning] [--require-reasoning]"
    exit 1
fi

MISSION_ID="$1"
INCLUDE_REASONING="true"
REQUIRE_REASONING="false"

shift
while [ $# -gt 0 ]; do
    case "$1" in
        --no-reasoning)
            INCLUDE_REASONING="false"
            ;;
        --require-reasoning)
            REQUIRE_REASONING="true"
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
    shift
done

echo "Syncing mission '${MISSION_ID}' to operational memory..."
echo "Memory API: ${MEMORY_API}"
echo "Include reasoning: ${INCLUDE_REASONING}"
echo "Require reasoning: ${REQUIRE_REASONING}"
echo ""

curl -s -X POST \
    "${MEMORY_API}/api/v1/memory/sync/${MISSION_ID}" \
    -H "Content-Type: application/json" \
    -d "{\"include_reasoning\": ${INCLUDE_REASONING}, \"require_reasoning\": ${REQUIRE_REASONING}}" \
    | python3 -m json.tool

echo ""
echo "Done."
