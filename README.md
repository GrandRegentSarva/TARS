# TARS -- Autonomous Drone Observability & Learning Platform

> **Existing drone platforms monitor missions. Our platform learns from missions.**
>
> Every failure, mitigation, outcome, agent decision, and evaluation becomes operational knowledge that improves future mission recommendations.

---

## What Is TARS?

TARS is a runtime feedback system for autonomous drones. It lets drone agents continuously **trace, evaluate, and introspect** their own behavior -- detecting telemetry anomalies, decision inconsistencies, and mission failures to iteratively refine future actions.

Built with: PX4, Gazebo, MAVSDK, Python (future: Gemini, Phoenix, Neo4j)

---

## Current Status: Phase 2 -- Mission Replay System

Phase 2 makes telemetry reusable. Missions are imported from Phase 1 JSON files into PostgreSQL, then queried and replayed through a FastAPI REST API.

### What's Working

**Phase 1 -- Mission Foundation:**
- [x] PX4 SITL + Gazebo headless simulation (Docker)
- [x] MAVSDK async telemetry collection (position, battery, GPS, attitude, health)
- [x] Autonomous mission execution (takeoff -> waypoints -> land)
- [x] Fault injection (GPS block, GPS noise, battery drain, baro offset, mag offset)
- [x] Structured JSON telemetry output with Pydantic models
- [x] Pre-built fault scenarios (GPS degradation, altitude confusion, sensor cascade)

**Phase 2 -- Mission Replay System:**
- [x] PostgreSQL mission store (Docker Compose)
- [x] Alembic database migrations
- [x] Mission import from Phase 1 JSON (validated through MissionTelemetry model)
- [x] Idempotent import with overwrite control
- [x] FastAPI REST API (mission listing, detail, events, replay)
- [x] Ordered replay frames with elapsed timing metadata
- [x] Fault event persistence and retrieval
- [x] Tests for importer, replay, and API endpoints

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

# Run a mission with a fault scenario (faults recorded in output JSON)
FAULT_SCENARIO=s1 ./scripts/run_mission.sh
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
PYTHONPATH=src .venv/bin/python3 -m tars.phase1.fault_injector
```

### 6. Stop the Simulation

```bash
./scripts/start_simulation.sh --stop
```

---

## Project Structure

```
TARS/
|-- plans/                              # Architecture and planning docs
|   |-- phase-1-mission-foundation.md
|   +-- phase-2-mission-replay-system.md
|-- docker/                             # Docker setup
|   |-- Dockerfile.px4-sitl             # PX4 SITL + Gazebo headless
|   +-- docker-compose.yml              # PX4 SITL + PostgreSQL
|-- src/
|   +-- tars/
|       |-- phase1/                     # Phase 1 -- Mission Foundation
|       |   |-- telemetry_collector.py  # Async telemetry streaming via MAVSDK
|       |   |-- mission_runner.py       # Autonomous mission execution
|       |   |-- fault_injector.py       # Fault injection + scenarios
|       |   +-- models/
|       |       +-- telemetry.py        # Pydantic data models
|       +-- phase2/                     # Phase 2 -- Mission Replay System
|           |-- api.py                  # FastAPI app and routes
|           |-- config.py              # Environment settings
|           |-- database.py            # Async SQLAlchemy engine/session
|           |-- importer.py            # Phase 1 JSON import + validation
|           |-- replay.py              # Replay frame construction
|           |-- service.py             # Mission query orchestration
|           +-- models/
|               |-- db.py              # SQLAlchemy ORM tables
|               +-- schemas.py         # API request/response schemas
|-- migrations/                         # Alembic database migrations
|   |-- env.py
|   +-- versions/
|-- scripts/
|   |-- start_simulation.sh             # Launch/stop PX4 simulation
|   |-- run_mission.sh                  # Run a Phase 1 mission
|   |-- start_replay_api.sh             # Start Phase 2 API server
|   +-- import_mission.sh               # Import mission JSON via API
|-- tests/
|   +-- phase2/                         # Phase 2 tests
|       |-- test_importer.py
|       |-- test_replay.py
|       +-- test_api.py
|-- output/                             # Telemetry JSON files
|-- alembic.ini                         # Alembic configuration
|-- pytest.ini                          # Pytest configuration
|-- requirements.txt                    # Python dependencies
|-- .env.example                        # Configuration template
+-- README.md
```

---

## Phase 2 -- Mission Replay System

Phase 2 runs independently of PX4/Gazebo. You only need PostgreSQL and the Phase 2 API.

### 1. Start PostgreSQL

```bash
docker compose -f docker/docker-compose.yml up postgres -d
```

### 2. Run Database Migrations

```bash
PYTHONPATH=src .venv/bin/alembic upgrade head
```

### 3. Start the Replay API

```bash
./scripts/start_replay_api.sh

# API docs available at http://localhost:8000/docs
# Health check at http://localhost:8000/health
```

### 4. Import a Mission

```bash
# Via the script (requires API running)
./scripts/import_mission.sh output/mission_20260608_120000.json

# Or via curl
curl -X POST http://localhost:8000/api/v1/missions/import \
  -H "Content-Type: application/json" \
  -d '{"path": "output/mission_20260608_120000.json", "overwrite": false}'
```

### 5. Query Missions

```bash
# List all missions
curl http://localhost:8000/api/v1/missions

# Get mission detail (includes faults)
curl http://localhost:8000/api/v1/missions/mission_20260608_120000

# Get telemetry events
curl http://localhost:8000/api/v1/missions/mission_20260608_120000/events

# Replay a mission
curl http://localhost:8000/api/v1/missions/mission_20260608_120000/replay

# Replay with time range
curl "http://localhost:8000/api/v1/missions/mission_20260608_120000/replay?from_ms=5000&to_ms=30000"
```

### 6. Run Tests

```bash
# Requires PostgreSQL running
PYTHONPATH=src .venv/bin/pytest tests/phase2/ -v
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
PYTHONPATH=src .venv/bin/python3 -m tars.phase1.fault_injector
```

Available commands:
| Command | Fault | Effect |
|---------|-------|--------|
| `1` | GPS Block | Complete GPS signal loss |
| `2` | GPS Noise | Noisy/jumpy GPS readings |
| `3` | Battery Drain | Accelerated battery discharge |
| `4` | Baro Offset | Incorrect altitude readings |
| `5` | Mag Offset | Corrupted compass heading |
| `6` | Wind | 8 m/s wind from north with moderate turbulence |
| `7` | Restore All | Remove all injected faults |

### Pre-built Scenarios

| Scenario | Inspired By | What Happens |
|----------|-------------|-------------|
| `s1` -- GPS Degradation | NASA Ingenuity | Progressive GPS noise -> block |
| `s2` -- Altitude Confusion | Amazon MK30 | Conflicting altitude sensors |
| `s3` -- Sensor Cascade | Bell 525 | Multiple sensors fail simultaneously |
| `s4` -- Wind Shear | Drone delivery incidents | Progressive crosswind -> severe gust |

---

## Configuration

Edit `.env` or set environment variables:

### Phase 1

| Variable | Default | Description |
|----------|---------|-------------|
| `PX4_CONNECTION` | `udp://:14540` | MAVSDK connection string |
| `TELEMETRY_RATE_HZ` | `1` | Snapshots per second |
| `DRONE_ID` | `tars-sim-01` | Drone identifier |
| `OUTPUT_DIR` | `output` | Telemetry output directory |
| `MISSION_ID` | auto-generated | Mission identifier |
| `FAULT_SCENARIO` | *(none)* | Run a fault scenario during the mission (`s1`–`s4`) |

### Phase 2

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `postgresql+asyncpg://tars:tars@localhost:5432/tars` | PostgreSQL connection string |
| `API_HOST` | `0.0.0.0` | FastAPI server host |
| `API_PORT` | `8000` | FastAPI server port |

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
| 1 | Mission Foundation (PX4 + Gazebo + MAVSDK) | ✅ Done |
| 2 | Mission Replay System (FastAPI + PostgreSQL) | ✅ Current |
| 3 | State Engine (Python + Redis) | Next |
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
