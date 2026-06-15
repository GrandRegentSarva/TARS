#!/usr/bin/env bash
# Query similar incidents from the Phase 7 operational memory graph.
#
# Usage:
#   ./scripts/query_similar_incidents.sh <incident_id>
#   ./scripts/query_similar_incidents.sh <incident_id> --limit 10
#
# Requires:
#   - Phase 7 Memory API running (./scripts/start_memory_api.sh)
#   - At least one mission synced

set -euo pipefail

MEMORY_API="${MEMORY_API_URL:-http://localhost:8005}"

if [ $# -lt 1 ]; then
    echo "Usage: $0 <incident_id> [--limit N]"
    exit 1
fi

INCIDENT_ID="$1"
LIMIT="20"

shift
while [ $# -gt 0 ]; do
    case "$1" in
        --limit)
            LIMIT="$2"
            shift
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
    shift
done

echo "Querying similar incidents for '${INCIDENT_ID}'..."
echo "Memory API: ${MEMORY_API}"
echo "Limit: ${LIMIT}"
echo ""

curl -s \
    "${MEMORY_API}/api/v1/memory/incidents/${INCIDENT_ID}/similar?limit=${LIMIT}" \
    | python3 -m json.tool

echo ""
echo "Done."
