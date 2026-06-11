#!/bin/bash
# =============================================================================
# TARS -- Run a Mission with Telemetry Collection
# =============================================================================
# This script runs the mission runner, which:
# 1. Connects to PX4 SITL
# 2. Starts telemetry collection
# 3. Flies the drone through a square waypoint pattern
# 4. Saves all telemetry to a JSON file in output/
#
# Prerequisites:
#   - PX4 SITL must be running (./scripts/start_simulation.sh)
#   - Python venv set up (python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt)
#
# Usage:
#   ./scripts/run_mission.sh                           # Default mission
#   MISSION_ID=test_001 ./scripts/run_mission.sh       # Custom mission ID
#   TELEMETRY_RATE_HZ=5 ./scripts/run_mission.sh       # 5 Hz collection
# =============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${BLUE}============================================${NC}"
echo -e "${BLUE}  TARS -- Mission Runner${NC}"
echo -e "${BLUE}============================================${NC}"

# Check for venv
if [ ! -d "$PROJECT_DIR/.venv" ]; then
    echo -e "${RED}Error: .venv not found. Create it first:${NC}"
    echo "  python3 -m venv .venv"
    echo "  . .venv/bin/activate"
    echo "  pip install -r requirements.txt"
    exit 1
fi

# Load .env if it exists
if [ -f "$PROJECT_DIR/.env" ]; then
    echo -e "${YELLOW}Loading .env configuration...${NC}"
    export $(grep -v '^#' "$PROJECT_DIR/.env" | xargs)
fi

# Set defaults if not already set
export PX4_CONNECTION="${PX4_CONNECTION:-udp://:14540}"
export TELEMETRY_RATE_HZ="${TELEMETRY_RATE_HZ:-1}"
export DRONE_ID="${DRONE_ID:-tars-sim-01}"
export OUTPUT_DIR="${OUTPUT_DIR:-output}"
export MISSION_ID="${MISSION_ID:-mission_$(date +%Y%m%d_%H%M%S)}"
# FAULT_SCENARIO is optional -- pass through if set (s1, s2, s3, s4)
export FAULT_SCENARIO="${FAULT_SCENARIO:-}"

echo -e "${YELLOW}Configuration:${NC}"
echo "  Mission ID:  $MISSION_ID"
echo "  Connection:  $PX4_CONNECTION"
echo "  Rate:        ${TELEMETRY_RATE_HZ} Hz"
echo "  Drone ID:    $DRONE_ID"
echo "  Output:      $OUTPUT_DIR/"
if [ -n "$FAULT_SCENARIO" ]; then
    echo "  Fault:       scenario $FAULT_SCENARIO"
fi
echo ""

# Create output directory
mkdir -p "$PROJECT_DIR/$OUTPUT_DIR"

# Run the mission using the venv Python
echo -e "${GREEN}Starting mission...${NC}"
cd "$PROJECT_DIR" && PYTHONPATH="$PROJECT_DIR/src" .venv/bin/python3 -m tars.phase1.mission_runner
