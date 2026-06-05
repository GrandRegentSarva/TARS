#!/bin/bash
# =============================================================================
# TARS -- Start PX4 SITL + Gazebo Headless Simulation
# =============================================================================
# This script builds and launches the Docker container running PX4 SITL
# with Gazebo in headless mode (no 3D GUI).
#
# What happens when you run this:
# 1. Docker builds the image (first time only -- takes 15-30 min)
# 2. Container starts with PX4 SITL + Gazebo headless
# 3. PX4 initializes and waits for commands on UDP port 14540
# 4. QGroundControl can connect on UDP port 14550
#
# Usage:
#   ./scripts/start_simulation.sh          # Build and start
#   ./scripts/start_simulation.sh --build  # Force rebuild
#   ./scripts/start_simulation.sh --stop   # Stop simulation
#   ./scripts/start_simulation.sh --logs   # View logs
# =============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
DOCKER_DIR="$PROJECT_DIR/docker"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}============================================${NC}"
echo -e "${BLUE}  TARS -- PX4 SITL Simulation Manager${NC}"
echo -e "${BLUE}============================================${NC}"

case "${1:-start}" in
    start)
        echo -e "${YELLOW}Starting PX4 SITL + Gazebo (headless)...${NC}"
        echo -e "${YELLOW}First build may take 15-30 minutes (downloading PX4 source + compiling)${NC}"
        echo ""
        cd "$DOCKER_DIR" && docker compose up --build
        ;;
    --build)
        echo -e "${YELLOW}Force rebuilding Docker image...${NC}"
        cd "$DOCKER_DIR" && docker compose build --no-cache
        echo -e "${GREEN}Build complete. Run './scripts/start_simulation.sh' to start.${NC}"
        ;;
    --stop)
        echo -e "${YELLOW}Stopping simulation...${NC}"
        cd "$DOCKER_DIR" && docker compose down
        echo -e "${GREEN}Simulation stopped.${NC}"
        ;;
    --logs)
        echo -e "${YELLOW}Showing simulation logs (Ctrl+C to exit)...${NC}"
        cd "$DOCKER_DIR" && docker compose logs -f
        ;;
    --status)
        echo -e "${YELLOW}Container status:${NC}"
        docker ps --filter "name=tars-px4-sitl" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
        ;;
    --help)
        echo "Usage: $0 [command]"
        echo ""
        echo "Commands:"
        echo "  start    Start simulation (default)"
        echo "  --build  Force rebuild Docker image"
        echo "  --stop   Stop simulation"
        echo "  --logs   View simulation logs"
        echo "  --status Show container status"
        echo "  --help   Show this help"
        ;;
    *)
        echo -e "${RED}Unknown command: $1${NC}"
        echo "Run '$0 --help' for usage."
        exit 1
        ;;
esac
