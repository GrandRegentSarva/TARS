#!/usr/bin/env bash
# Process a mission through the Phase 4 Incident Engine.
#
# Usage:
#   ./scripts/process_mission_incidents.sh <mission_id>
#
# Requires:
#   - Phase 4 Incident API running (./scripts/start_incident_api.sh)

set -euo pipefail

MISSION_ID="${1:?Usage: $0 <mission_id>}"
API_URL="${INCIDENT_API_URL:-http://localhost:8003}"

echo "Processing incidents for mission: ${MISSION_ID}"
echo "Incident API: ${API_URL}"

curl -s -X POST \
    "${API_URL}/api/v1/incidents/process/${MISSION_ID}" \
    -H "Content-Type: application/json" \
    -d '{}' | python3 -m json.tool

echo ""
echo "Query incidents:"
echo "  curl ${API_URL}/api/v1/incidents/${MISSION_ID}"
