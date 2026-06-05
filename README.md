# TARS -- Autonomous Drone Observability & Learning Platform

> **Existing drone platforms monitor missions. Our platform learns from missions.**
>
> Every failure, mitigation, outcome, agent decision, and evaluation becomes operational knowledge that improves future mission recommendations.

---

## What Is TARS?

TARS is a runtime feedback system for autonomous drones. It lets drone agents continuously **trace, evaluate, and introspect** their own behavior -- detecting telemetry anomalies, decision inconsistencies, and mission failures to iteratively refine future actions.

Built with: PX4, Gazebo, MAVSDK, Python (future: Gemini, Phoenix, Neo4j)

---

## Current Status: Phase 1 -- Mission Foundation

Phase 1 proves that telemetry exists. A simulated drone flies autonomous missions while structured telemetry is collected and faults are injected.

### What's Working

- [x] PX4 SITL + Gazebo headless simulation (Docker)
- [x] MAVSDK async telemetry collection (position, battery, GPS, attitude, health)
- [x] Autonomous mission execution (takeoff -> waypoints -> land)
- [x] Fault injection (GPS block, GPS noise, battery drain, baro offset, mag offset)
- [x] Structured JSON telemetry output with Pydantic models
- [x] Pre-built fault scenarios (GPS degradation, altitude confusion, sensor cascade)

---

## Quick Start

### Prerequisites

- **Docker** 24+ with Docker Compose v2
- **Python** 3.10+
- **~10GB disk space** for PX4 Docker image (one-time download)
- **Optional:** [QGroundControl](https://docs.qgroundcontrol.com/master/en/qgc-user-guide/getting_started/download_and_install.html) for visual drone tracking

### 1. Clone and Setup

```bash
cd ~/Desktop/Projects/TARS

# Copy environment config
cp .env.example .env

# Create a Python virtual environment and install dependencies
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

### 2. Start the Simulation

```bash
# First run builds the Docker image (~15-30 min, downloads PX4 source + compiles)
./scripts/start_simulation.sh

# Wait until you see "Ready for takeoff" in the logs
```

> **Note:** The first build takes a while because it clones and compiles the entire PX4 firmware. Subsequent starts are fast (~10 seconds).

### 3. Run a Mission (in a new terminal)

```bash
# Activate the venv first
. .venv/bin/activate

# Run the default square mission with telemetry collection
./scripts/run_mission.sh

# Or with a custom mission ID
MISSION_ID=my_first_mission ./scripts/run_mission.sh
```

### 4. View the Output

```bash
# Telemetry is saved as JSON in output/
cat output/mission_*.json | python3 -m json.tool | head -50
```

### 5. Inject Faults (in another terminal)

```bash
# Activate the venv first
. .venv/bin/activate

# Interactive fault injection while a mission is running
.venv/bin/python3 -m src.phase1.fault_injector
```

### 6. Stop the Simulation

```bash
./scripts/start_simulation.sh --stop
```

---

## Project Structure

```
TARS/
|-- plans/                          # Architecture and planning docs
|   +-- phase-1-mission-foundation.md
|-- docker/                         # Docker setup
|   |-- Dockerfile.px4-sitl         # PX4 SITL + Gazebo headless
|   +-- docker-compose.yml          # Container orchestration
|-- src/
|   +-- phase1/
|       |-- telemetry_collector.py  # Async telemetry streaming via MAVSDK
|       |-- mission_runner.py       # Autonomous mission execution
|       |-- fault_injector.py       # Fault injection + scenarios
|       +-- models/
|           +-- telemetry.py        # Pydantic data models
|-- scripts/
|   |-- start_simulation.sh         # Launch/stop simulation
|   +-- run_mission.sh              # Run a mission
|-- output/                         # Telemetry JSON files
|-- requirements.txt                # Python dependencies
|-- .env.example                    # Configuration template
+-- README.md
```

---

## Telemetry Output Format

Each mission produces a JSON file in `output/`:

```json
{
  "mission_id": "mission_001",
  "drone_id": "tars-sim-01",
  "start_time": "2024-01-15T10:30:00Z",
  "end_time": "2024-01-15T10:35:42Z",
  "faults_injected": [],
  "telemetry": [
    {
      "timestamp": "2024-01-15T10:30:01Z",
      "position": {
        "latitude_deg": 47.3977,
        "longitude_deg": 8.5456,
        "absolute_altitude_m": 488.5,
        "relative_altitude_m": 22.3
      },
      "battery": {
        "voltage_v": 11.8,
        "remaining_percent": 87.0
      },
      "gps": {
        "num_satellites": 12,
        "fix_type": "FIX_3D"
      },
      "attitude": {
        "roll_deg": 2.1,
        "pitch_deg": -1.3,
        "yaw_deg": 145.7
      },
      "flight_mode": "MISSION",
      "health": {
        "is_gyrometer_calibration_ok": true,
        "is_accelerometer_calibration_ok": true,
        "is_magnetometer_calibration_ok": true,
        "is_home_position_ok": true,
        "is_global_position_ok": true
      }
    }
  ],
  "mission_result": "SUCCESS",
  "summary": {
    "total_snapshots": 342,
    "duration_seconds": 342.0,
    "max_altitude_m": 22.5,
    "distance_traveled_m": 450.2,
    "min_battery_percent": 81.2,
    "max_speed_m_s": 5.2,
    "collection_rate_hz": 1.0
  }
}
```

---

## Fault Injection

### Interactive Mode

```bash
.venv/bin/python3 -m src.phase1.fault_injector
```

Available commands:
| Command | Fault | Effect |
|---------|-------|--------|
| `1` | GPS Block | Complete GPS signal loss |
| `2` | GPS Noise | Noisy/jumpy GPS readings |
| `3` | Battery Drain | Accelerated battery discharge |
| `4` | Baro Offset | Incorrect altitude readings |
| `5` | Mag Offset | Corrupted compass heading |
| `6` | Restore All | Remove all injected faults |

### Pre-built Scenarios

| Scenario | Inspired By | What Happens |
|----------|-------------|-------------|
| `s1` -- GPS Degradation | NASA Ingenuity | Progressive GPS noise -> block |
| `s2` -- Altitude Confusion | Amazon MK30 | Conflicting altitude sensors |
| `s3` -- Sensor Cascade | Bell 525 | Multiple sensors fail simultaneously |

---

## Configuration

Edit `.env` or set environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `PX4_CONNECTION` | `udp://:14540` | MAVSDK connection string |
| `TELEMETRY_RATE_HZ` | `1` | Snapshots per second |
| `DRONE_ID` | `tars-sim-01` | Drone identifier |
| `OUTPUT_DIR` | `output` | Telemetry output directory |
| `MISSION_ID` | auto-generated | Mission identifier |

---

## Hardware Notes

Developed and tested on:
- **CPU:** Intel i3-6100U (2C/4T @ 2.3GHz)
- **RAM:** 8GB
- **GPU:** Intel HD 520 (integrated)
- **OS:** Pop!_OS 22.04

Gazebo runs in **headless mode** (no 3D rendering) to fit within RAM constraints. Use [QGroundControl](https://docs.qgroundcontrol.com/master/en/qgc-user-guide/getting_started/download_and_install.html) on the host for visual drone tracking on a 2D map.

---

## Roadmap

| Phase | Name | Status |
|-------|------|--------|
| 1 | Mission Foundation (PX4 + Gazebo + MAVSDK) | Current |
| 2 | Mission Replay System (FastAPI + PostgreSQL) | Next |
| 3 | State Engine (Python + Redis) | Planned |
| 4 | Incident Engine (Rules + Statistical Detection) | Planned |
| 5 | Gemini Reasoning Layer (Google ADK) | Planned |
| 6 | Phoenix Integration (OpenInference Tracing) | Planned |
| 7 | Neo4j Operational Memory | Planned |
| 8 | Phoenix MCP (Self-Introspection) | Planned |
| 9 | Evaluation Layer | Planned |
| 10 | Learning Engine | Planned |
| 11 | Knowledge Validation | Planned |
| 12 | Adaptive Recommendation Engine | Planned |

---

## License

MIT
