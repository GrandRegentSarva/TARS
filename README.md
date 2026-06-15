# TARS -- Autonomous Drone Observability & Learning Platform

> **Existing drone platforms monitor missions. Our platform learns from missions.**
>
> Every failure, mitigation, outcome, agent decision, and evaluation becomes operational knowledge that improves future mission recommendations.

---

## What Is TARS?

TARS is a runtime feedback system for autonomous drones. It lets drone agents continuously **trace, evaluate, and introspect** their own behavior — detecting telemetry anomalies, decision inconsistencies, and mission failures to iteratively refine future actions.

Built with PX4, Gazebo, MAVSDK, Python, Gemini, Phoenix, Neo4j, and Redis.

---

## Architecture

TARS is organized as a layered pipeline. Each layer builds on the one below it:

| Layer | What It Does | Port |
|-------|-------------|------|
| **Phase 1 — Mission Foundation** | Runs PX4 SITL + Gazebo headless simulations, collects async telemetry via MAVSDK, injects faults (GPS block, battery drain, sensor cascade, etc.), and writes structured JSON output. | — |
| **Phase 2 — Mission Replay** | Imports mission JSON into PostgreSQL, provides ordered replay frames with elapsed timing, and exposes a FastAPI REST API for mission queries. | 8000 |
| **Phase 3 — State Engine** | Transforms replay frames into classified mission states (phase, health, risk score) and stores them as Redis timelines. Deterministic phase classification and additive risk scoring. | 8002 |
| **Phase 4 — Incident Engine** | Evaluates state timelines against 7 rule types across 4 severity levels. Collapses consecutive matches into bounded incidents with gap-based merging and persistence thresholds. | 8003 |
| **Phase 5 — Gemini Reasoning** | Analyzes bounded incidents using Google Gemini (via ADK) to produce structured, advisory-only root-cause assessments. Provider-neutral interface with versioned prompts and control-command rejection at the model boundary. | 8004 |
| **Phase 6 — Phoenix Integration** | Instruments the reasoning layer with OpenTelemetry tracing and exports spans to [Arize Phoenix](https://phoenix.arize.com/). Produces parent-child span hierarchies with OpenInference semantic conventions and configurable content capture (full / metadata / disabled). | — |
| **Phase 7 — Operational Memory** | Projects bounded facts from Phases 2, 4, and 5 into a Neo4j graph. Connects missions → incidents → root causes → mitigations → outcomes. Answers "Have we seen this before?" with provenance-preserving history queries. | 8005 |

Each phase has its own FastAPI service, test suite, and configuration. Phases communicate over HTTP — no shared databases, no tight coupling.

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
|   |-- phase-2-mission-replay-system.md
|   |-- phase-3-state-engine.md
|   |-- phase-4-incident-engine.md
|   |-- phase-5-gemini-reasoning-layer.md
|   |-- phase-6-phoenix-integration.md
|   +-- phase-7-neo4j-operational-memory.md
|-- docker/                             # Docker setup
|   |-- Dockerfile.px4-sitl             # PX4 SITL + Gazebo headless
|   +-- docker-compose.yml              # PX4 SITL + PostgreSQL + Redis + Neo4j
|-- src/
|   +-- tars/
|       |-- phase1/                     # Phase 1 -- Mission Foundation
|       |   |-- telemetry_collector.py  # Async telemetry streaming via MAVSDK
|       |   |-- mission_runner.py       # Autonomous mission execution
|       |   |-- fault_injector.py       # Fault injection + scenarios
|       |   +-- models/
|       |       +-- telemetry.py        # Pydantic data models
|       |-- phase2/                     # Phase 2 -- Mission Replay System
|       |   |-- api.py                  # FastAPI app and routes
|       |   |-- config.py              # Environment settings
|       |   |-- database.py            # Async SQLAlchemy engine/session
|       |   |-- importer.py            # Phase 1 JSON import + validation
|       |   |-- replay.py              # Replay frame construction
|       |   |-- service.py             # Mission query orchestration
|       |   +-- models/
|       |       |-- db.py              # SQLAlchemy ORM tables
|       |       +-- schemas.py         # API request/response schemas
|       |-- phase3/                     # Phase 3 -- State Engine
|       |   |-- api.py                  # FastAPI app (port 8002)
|       |   |-- config.py              # Environment settings
|       |   |-- models.py              # Pydantic models and enums
|       |   |-- phase_classifier.py    # Deterministic phase rules
|       |   |-- risk.py                # Risk scoring and health assessment
|       |   |-- state_processor.py     # Frame-to-state transformation
|       |   |-- store.py               # Async Redis state store
|       |   |-- replay_client.py       # HTTP client for Phase 2 API
|       |   +-- service.py             # Processing orchestration
|       |-- phase4/                     # Phase 4 -- Incident Engine
|       |   |-- api.py                  # FastAPI app (port 8003)
|       |   |-- config.py              # Environment settings
|       |   |-- models.py              # Incident enums and schemas
|       |   |-- rules.py               # Deterministic state rules
|       |   |-- statistics.py          # Rolling windows and trend detection
|       |   |-- detector.py            # Incident collapser
|       |   |-- store.py               # Async Redis incident store
|       |   |-- state_client.py        # HTTP client for Phase 3 API
|       |   +-- service.py             # Detection orchestration
|       |-- phase5/                     # Phase 5 -- Gemini Reasoning Layer
|       |   |-- api.py                  # FastAPI app (port 8004)
|       |   |-- config.py              # Environment settings
|       |   |-- models.py              # Reasoning schemas and provider protocol
|       |   |-- prompts.py             # Versioned system instruction and prompt
|       |   |-- agent.py               # Google ADK Gemini agent configuration
|       |   |-- provider.py            # Gemini + fake reasoning providers
|       |   |-- incident_client.py     # HTTP client for Phase 4 API
|       |   |-- store.py               # Async Redis reasoning store
|       |   +-- service.py             # Reasoning orchestration
|       |-- phase6/                     # Phase 6 -- Phoenix Integration
|       |   |-- config.py              # PhoenixSettings (env-driven)
|       |   |-- attributes.py          # Stable trace attribute constants
|       |   +-- tracing.py             # TracerProvider setup, OTLP exporter
|       +-- phase7/                     # Phase 7 -- Operational Memory
|           |-- api.py                  # FastAPI app (port 8005)
|           |-- config.py              # Environment settings
|           |-- models.py              # Graph models, enums, request/response
|           |-- database.py            # Async Neo4j driver lifecycle
|           |-- schema.py             # Constraints and indexes
|           |-- mapper.py             # Pure mapping + deterministic IDs
|           |-- repository.py         # Graph MERGE/MATCH operations
|           |-- service.py            # Sync + query orchestration
|           |-- phase2_client.py      # HTTP client for Phase 2 API
|           |-- phase4_client.py      # HTTP client for Phase 4 API
|           +-- phase5_client.py      # HTTP client for Phase 5 API
|-- migrations/                         # Alembic database migrations
|   |-- env.py
|   +-- versions/
|-- scripts/
|   |-- start_simulation.sh             # Launch/stop PX4 simulation
|   |-- run_mission.sh                  # Run a Phase 1 mission
|   |-- start_replay_api.sh             # Start Phase 2 API server
|   |-- import_mission.sh               # Import mission JSON via API
|   |-- start_state_api.sh              # Start Phase 3 State API server
|   |-- process_mission_state.sh        # Process a mission through Phase 3
|   |-- start_incident_api.sh           # Start Phase 4 Incident API server
|   |-- process_mission_incidents.sh    # Detect incidents for a mission
|   |-- start_reasoning_api.sh          # Start Phase 5 Reasoning API server
|   |-- analyze_incident.sh            # Analyze an incident through Phase 5
|   |-- start_memory_api.sh            # Start Phase 7 Memory API server
|   |-- sync_mission_memory.sh         # Sync a mission into Neo4j graph
|   +-- query_similar_incidents.sh     # Query similar historical incidents
|-- tests/
|   |-- phase2/                         # Phase 2 tests
|   |   |-- test_importer.py
|   |   |-- test_replay.py
|   |   +-- test_api.py
|   |-- phase3/                         # Phase 3 tests
|   |   |-- test_phase_classifier.py
|   |   |-- test_risk.py
|   |   |-- test_state_processor.py
|   |   |-- test_store.py
|   |   +-- test_api.py
|   |-- phase4/                         # Phase 4 tests
|   |   |-- test_rules.py
|   |   |-- test_statistics.py
|   |   |-- test_detector.py
|   |   |-- test_store.py
|   |   +-- test_api.py
|   |-- phase5/                         # Phase 5 tests
|   |   |-- test_models.py
|   |   |-- test_prompts.py
|   |   |-- test_client.py
|   |   |-- test_provider.py
|   |   |-- test_store.py
|   |   |-- test_service.py
|   |   +-- test_api.py
|   |-- phase6/                         # Phase 6 tests
|   |   |-- test_config.py              # 31 configuration tests
|   |   |-- test_tracing.py             # 14 tracing bootstrap tests
|   |   +-- test_reasoning_traces.py    # 44 reasoning trace tests
|   +-- phase7/                         # Phase 7 tests
|       |-- test_models.py              # Model validation tests
|       |-- test_mapper.py              # Mapping + deterministic ID tests
|       |-- test_clients.py             # Upstream HTTP client tests
|       |-- test_repository.py          # Graph operation tests
|       |-- test_service.py             # Service orchestration tests
|       +-- test_api.py                 # API endpoint tests
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

## Phase 3 -- State Engine

Phase 3 runs independently of PX4/Gazebo. You need Redis, the Phase 2 API (for replay data), and the Phase 3 State API.

### 1. Start Redis

```bash
docker compose -f docker/docker-compose.yml up redis -d
```

### 2. Start the Phase 2 Replay API

Phase 3 fetches replay frames from Phase 2, so the Phase 2 API must be running:

```bash
# Start PostgreSQL + run migrations if not already done
docker compose -f docker/docker-compose.yml up postgres -d
PYTHONPATH=src .venv/bin/alembic upgrade head
./scripts/start_replay_api.sh
```

### 3. Start the State API

```bash
./scripts/start_state_api.sh

# API docs available at http://localhost:8002/docs
# Health check at http://localhost:8002/health
```

### 4. Process a Mission

```bash
# Via the script (requires both APIs running)
./scripts/process_mission_state.sh mission_20260608_120000

# Or via curl
curl -X POST http://localhost:8002/api/v1/state/process/mission_20260608_120000 \
  -H "Content-Type: application/json" \
  -d '{}'

# Process with time range (partial replay -- does not update current state)
curl -X POST http://localhost:8002/api/v1/state/process/mission_20260608_120000 \
  -H "Content-Type: application/json" \
  -d '{"from_ms": 5000, "to_ms": 30000}'
```

### 5. Query State

```bash
# Get current state snapshot
curl http://localhost:8002/api/v1/state/mission_20260608_120000/current

# Get full state timeline
curl http://localhost:8002/api/v1/state/mission_20260608_120000/timeline

# Get timeline for a time range
curl "http://localhost:8002/api/v1/state/mission_20260608_120000/timeline?from_ms=5000&to_ms=30000"

# Get state at a specific time
curl http://localhost:8002/api/v1/state/mission_20260608_120000/at/15000

# Get processing status
curl http://localhost:8002/api/v1/state/mission_20260608_120000/status
```

### 6. Run Tests

```bash
# Pure logic tests (no Redis required)
PYTHONPATH=src .venv/bin/pytest tests/phase3/test_phase_classifier.py tests/phase3/test_risk.py tests/phase3/test_state_processor.py -v

# All tests including Redis integration (requires Redis running)
PYTHONPATH=src .venv/bin/pytest tests/phase3/ -v
```

---

## Phase 4 -- Incident Engine

Phase 4 runs independently of PX4/Gazebo. You need Redis, the Phase 3 State API (for state timelines), and the Phase 4 Incident API.

### 1. Start Redis and Phase 3

```bash
# Start Redis
docker compose -f docker/docker-compose.yml up redis -d

# Start Phase 2 + Phase 3 APIs (Phase 4 depends on Phase 3 timelines)
./scripts/start_replay_api.sh &
./scripts/start_state_api.sh &
```

### 2. Start the Incident API

```bash
./scripts/start_incident_api.sh

# API docs available at http://localhost:8003/docs
# Health check at http://localhost:8003/health
```

### 3. Process Mission Incidents

```bash
# Via the script (requires Phase 3 + Phase 4 APIs running)
./scripts/process_mission_incidents.sh mission_20260608_120000

# Or via curl
curl -X POST http://localhost:8003/api/v1/incidents/process/mission_20260608_120000 \
  -H "Content-Type: application/json" \
  -d '{}'
```

### 4. Query Incidents

```bash
# List all incidents for a mission
curl http://localhost:8003/api/v1/incidents/mission_20260608_120000

# List incidents within a time range
curl "http://localhost:8003/api/v1/incidents/mission_20260608_120000?from_ms=5000&to_ms=30000"

# Get a specific incident by ID
curl http://localhost:8003/api/v1/incidents/mission_20260608_120000/inc_abc123

# Get processing status
curl http://localhost:8003/api/v1/incidents/mission_20260608_120000/status
```

### 5. Run Tests

```bash
# Pure logic tests (no Redis required)
PYTHONPATH=src .venv/bin/pytest tests/phase4/test_rules.py tests/phase4/test_statistics.py tests/phase4/test_detector.py -v

# All tests including Redis integration (requires Redis running)
PYTHONPATH=src .venv/bin/pytest tests/phase4/ -v
```

---

## Phase 5 -- Gemini Reasoning Layer

Phase 5 runs independently of PX4/Gazebo. You need Redis, the Phase 4 Incident API (for incident data), and the Phase 5 Reasoning API.

### 1. Start Redis and Phase 4

```bash
# Start Redis
docker compose -f docker/docker-compose.yml up redis -d

# Start Phase 2 + Phase 3 + Phase 4 APIs
./scripts/start_replay_api.sh &
./scripts/start_state_api.sh &
./scripts/start_incident_api.sh &
```

### 2. Configure Gemini (Optional for Startup)

```bash
# Set your Gemini API key in .env
echo "GEMINI_API_KEY=your-key-here" >> .env

# Or export directly
export GEMINI_API_KEY=your-key-here
```

> **Note:** The API starts without a Gemini key but analysis endpoints will return configuration errors. Health endpoint reports `gemini: unconfigured`.

### 3. Start the Reasoning API

```bash
./scripts/start_reasoning_api.sh

# API docs available at http://localhost:8004/docs
# Health check at http://localhost:8004/health
```

### 4. Analyze an Incident

```bash
# Via the script (requires Phase 4 + Phase 5 APIs running)
./scripts/analyze_incident.sh mission_20260608_120000 inc_abc123

# Or via curl
curl -X POST http://localhost:8004/api/v1/reasoning/analyze/mission_20260608_120000/inc_abc123 \
  -H "Content-Type: application/json" \
  -d '{"overwrite": true}'
```

### 5. Query Analyses

```bash
# Get analysis for a specific incident
curl http://localhost:8004/api/v1/reasoning/mission_20260608_120000/inc_abc123

# List all analyses for a mission
curl http://localhost:8004/api/v1/reasoning/mission_20260608_120000

# Reuse existing analysis (no Gemini call)
curl -X POST http://localhost:8004/api/v1/reasoning/analyze/mission_20260608_120000/inc_abc123 \
  -H "Content-Type: application/json" \
  -d '{"overwrite": false}'
```

### 6. Run Tests

```bash
# Pure logic tests (no Redis or Gemini required)
PYTHONPATH=src .venv/bin/pytest tests/phase5/test_models.py tests/phase5/test_prompts.py tests/phase5/test_provider.py tests/phase5/test_client.py -v

# All tests including Redis integration (requires Redis running)
PYTHONPATH=src .venv/bin/pytest tests/phase5/ -v
```

---

## Phase 7 -- Operational Memory

Phase 7 projects bounded facts from Phases 2, 4, and 5 into a Neo4j graph database. It connects missions → incidents → root causes → mitigations → outcomes and answers "Have we seen this before?" with provenance-preserving history queries.

### 1. Start Neo4j and Upstream APIs

```bash
# Start Neo4j (+ PostgreSQL and Redis for upstream phases)
docker compose -f docker/docker-compose.yml up neo4j postgres redis -d

# Start Phase 2 + Phase 3 + Phase 4 + Phase 5 APIs
./scripts/start_replay_api.sh &
./scripts/start_state_api.sh &
./scripts/start_incident_api.sh &
./scripts/start_reasoning_api.sh &
```

### 2. Configure Neo4j

```bash
# Set your Neo4j password in .env (must match docker-compose)
echo "NEO4J_PASSWORD=tars" >> .env

# Or export directly
export NEO4J_PASSWORD=tars
```

> **Note:** The default Docker Compose configuration sets the Neo4j password to `tars`. Schema constraints and indexes are created automatically on API startup.

### 3. Start the Memory API

```bash
./scripts/start_memory_api.sh

# API docs available at http://localhost:8005/docs
# Health check at http://localhost:8005/health
```

### 4. Sync a Mission

```bash
# Via the script (requires upstream APIs running)
./scripts/sync_mission_memory.sh mission_20260608_120000

# Or via curl
curl -X POST http://localhost:8005/api/v1/memory/sync \
  -H "Content-Type: application/json" \
  -d '{"mission_id": "mission_20260608_120000"}'

# Check sync status
curl http://localhost:8005/api/v1/memory/sync/mission_20260608_120000
```

### 5. Query Operational Memory

```bash
# Get incident neighborhood (root causes, mitigations, outcomes)
curl http://localhost:8005/api/v1/memory/incidents/inc_abc123

# Find similar historical incidents
curl "http://localhost:8005/api/v1/memory/incidents/inc_abc123/similar?limit=10"

# Or via the script
./scripts/query_similar_incidents.sh inc_abc123
```

### 6. Record Mitigations and Outcomes

```bash
# Record an applied mitigation
curl -X POST http://localhost:8005/api/v1/memory/mitigations \
  -H "Content-Type: application/json" \
  -d '{
    "incident_id": "inc_abc123",
    "mitigation_text": "Switched to backup GPS receiver",
    "applied_by": "operator"
  }'

# Record an outcome
curl -X POST http://localhost:8005/api/v1/memory/outcomes \
  -H "Content-Type: application/json" \
  -d '{
    "incident_id": "inc_abc123",
    "status": "recovered",
    "description": "GPS signal restored after switching to backup receiver",
    "mitigation_application_id": "ma_xyz789"
  }'
```

### 7. Run Tests

```bash
# All Phase 7 tests (no Neo4j required -- all graph operations are mocked)
PYTHONPATH=src .venv/bin/pytest tests/phase7/ -v

# Individual test modules
PYTHONPATH=src .venv/bin/pytest tests/phase7/test_models.py tests/phase7/test_mapper.py -v
PYTHONPATH=src .venv/bin/pytest tests/phase7/test_clients.py tests/phase7/test_repository.py -v
PYTHONPATH=src .venv/bin/pytest tests/phase7/test_service.py tests/phase7/test_api.py -v
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

### Phase 3

| Variable | Default | Description |
|----------|---------|-------------|
| `REDIS_URL` | `redis://localhost:6379/0` | Redis connection string |
| `PHASE2_API_URL` | `http://localhost:8000` | Phase 2 Replay API base URL |
| `STATE_API_HOST` | `0.0.0.0` | State API server host |
| `STATE_API_PORT` | `8002` | State API server port |

### Phase 4

| Variable | Default | Description |
|----------|---------|-------------|
| `PHASE3_API_URL` | `http://localhost:8002` | Phase 3 State API base URL |
| `INCIDENT_API_HOST` | `0.0.0.0` | Incident API server host |
| `INCIDENT_API_PORT` | `8003` | Incident API server port |
| `INCIDENT_MAX_GAP_MS` | `5000` | Max gap between matches to merge |
| `INCIDENT_MIN_STATES` | `3` | Min states for persistence threshold |
| `INCIDENT_HIGH_RISK` | `0.8` | Risk threshold for immediate incident |
| `INCIDENT_ELEVATED_RISK` | `0.6` | Risk threshold for elevated detection |

### Phase 5

| Variable | Default | Description |
|----------|---------|-------------|
| `PHASE4_API_URL` | `http://localhost:8003` | Phase 4 Incident API base URL |
| `REASONING_API_HOST` | `0.0.0.0` | Reasoning API server host |
| `REASONING_API_PORT` | `8004` | Reasoning API server port |
| `INCIDENT_CLIENT_TIMEOUT` | `30.0` | HTTP client timeout for Phase 4 calls |
| `GEMINI_API_KEY` | *(empty)* | Gemini API key (required for live reasoning) |
| `GEMINI_MODEL` | `gemini-2.5-flash` | Gemini model identifier |
| `GEMINI_TEMPERATURE` | `0.1` | Gemini temperature (low for stable reasoning) |

### Phase 6

| Variable | Default | Description |
|----------|---------|-------------|
| `PHOENIX_ENABLED` | `true` | Enable/disable Phoenix tracing |
| `PHOENIX_ENDPOINT` | `http://localhost:6006` | Phoenix OTLP endpoint |
| `PHOENIX_PROJECT_NAME` | `tars-reasoning` | Phoenix project name |
| `PHOENIX_CONTENT_MODE` | `full` | Content capture: `full`, `metadata`, `disabled` |
| `PHOENIX_EXPORT_TIMEOUT_SECONDS` | `5` | OTLP export timeout |
| `PHOENIX_BATCH_EXPORT` | `true` | Use batch span processor |

### Phase 7

| Variable | Default | Description |
|----------|---------|-------------|
| `NEO4J_URI` | `bolt://localhost:7687` | Neo4j Bolt connection URI |
| `NEO4J_USER` | `neo4j` | Neo4j username |
| `NEO4J_PASSWORD` | *(empty)* | Neo4j password |
| `NEO4J_DATABASE` | `neo4j` | Neo4j database name |
| `MEMORY_API_HOST` | `0.0.0.0` | Memory API server host |
| `MEMORY_API_PORT` | `8005` | Memory API server port |
| `PHASE2_API_URL` | `http://localhost:8000` | Phase 2 Replay API base URL |
| `PHASE4_API_URL` | `http://localhost:8003` | Phase 4 Incident API base URL |
| `PHASE5_API_URL` | `http://localhost:8004` | Phase 5 Reasoning API base URL |
| `MEMORY_CLIENT_TIMEOUT` | `30.0` | HTTP client timeout for upstream calls |
| `MEMORY_QUERY_DEFAULT_LIMIT` | `20` | Default result limit for queries |
| `MEMORY_QUERY_MAX_LIMIT` | `100` | Maximum result limit for queries |

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
| 2 | Mission Replay System (FastAPI + PostgreSQL) | ✅ Done |
| 3 | State Engine (Python + Redis) | ✅ Done |
| 4 | Incident Engine (Rules + Statistical Detection) | ✅ Done |
| 5 | Gemini Reasoning Layer (Google ADK) | ✅ Done |
| 6 | Phoenix Integration (OpenInference Tracing) | ✅ Done |
| 7 | Neo4j Operational Memory | ✅ Current |
| 8 | Phoenix MCP (Self-Introspection) | Planned |
| 9 | Evaluation Layer | Planned |
| 10 | Learning Engine | Planned |
| 11 | Knowledge Validation | Planned |
| 12 | Adaptive Recommendation Engine | Planned |

---

## License

MIT
