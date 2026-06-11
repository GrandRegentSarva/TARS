#!/usr/bin/env bash
# =============================================================================
# Process Mission State via Phase 3 API
# =============================================================================
# Usage:
#   ./scripts/process_mission_state.sh <mission_id>
#   ./scripts/process_mission_state.sh mission_20260608_120000
#
# Prerequisites:
#   - Phase 3 State Engine API running on port 8002
#   - Phase 2 Replay API running on port 8000
#   - Redis running
#   - curl installed
#
# This script triggers state processing for a mission and then
# queries the resulting current state.
# =============================================================================

set -euo pipefail

if [ $# -lt 1 ]; then
    echo "Usage: $0 <mission_id>"
    echo "Example: $0 mission_20260608_120000"
    exit 1
fi

MISSION_ID="$1"
STATE_API="${STATE_API_URL:-http://localhost:8002}"

echo "=== Processing Mission State ==="
echo "Mission:    $MISSION_ID"
echo "State API:  $STATE_API"
echo "================================"

# Step 1: Trigger state processing
echo ""
echo ">>> POST /api/v1/state/process/$MISSION_ID"
curl -s -X POST \
    "${STATE_API}/api/v1/state/process/${MISSION_ID}" \
    -H "Content-Type: application/json" \
    -d '{"overwrite": true}' | python3 -m json.tool

# Step 2: Query current state
echo ""
echo ">>> GET /api/v1/state/$MISSION_ID/current"
curl -s "${STATE_API}/api/v1/state/${MISSION_ID}/current" | python3 -m json.tool

# Step 3: Query processing status
echo ""
echo ">>> GET /api/v1/state/$MISSION_ID/status"
curl -s "${STATE_API}/api/v1/state/${MISSION_ID}/status" | python3 -m json.tool

echo ""
echo "=== Done ==="
