#!/usr/bin/env bash
# Analyze a Phase 4 incident through the Phase 5 Reasoning API.
#
# Usage:
#   ./scripts/analyze_incident.sh <mission_id> <incident_id>
#
# Requires:
#   - Phase 5 Reasoning API running (./scripts/start_reasoning_api.sh)

set -euo pipefail

MISSION_ID="${1:?Usage: $0 <mission_id> <incident_id>}"
INCIDENT_ID="${2:?Usage: $0 <mission_id> <incident_id>}"
API_URL="${REASONING_API_URL:-http://localhost:8004}"

echo "Analyzing incident: ${INCIDENT_ID}"
echo "Mission: ${MISSION_ID}"
echo "Reasoning API: ${API_URL}"
echo ""

curl -s -X POST \
    "${API_URL}/api/v1/reasoning/analyze/${MISSION_ID}/${INCIDENT_ID}" \
    -H "Content-Type: application/json" \
    -d '{"overwrite": true}' | python3 -m json.tool

echo ""
echo "Query analysis:"
echo "  curl ${API_URL}/api/v1/reasoning/${MISSION_ID}/${INCIDENT_ID}"
echo ""
echo "List all analyses for mission:"
echo "  curl ${API_URL}/api/v1/reasoning/${MISSION_ID}"
