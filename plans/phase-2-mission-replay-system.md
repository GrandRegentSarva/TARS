# Phase 2 -- Mission Replay System

> **Objective:** Turn Phase 1 telemetry files into replayable mission records.
> Without replay, later state, incident, reasoning, evaluation, and learning layers have no reliable historical substrate.

---

## Scope

Phase 2 is a persistence and replay layer for completed missions.

It should answer:

- "What missions have we flown?"
- "Show mission 17."
- "Replay mission 17 from timestamp 0 to N."
- "What faults were active during that replay?"
- "Give Phase 3 a clean ordered stream of telemetry events."

Phase 2 should not do incident detection, AI reasoning, Redis state computation, Neo4j memory, Phoenix tracing, or Kafka streaming. Those belong to later phases.

---

## Phase 1 Handoff

Phase 1 now emits complete mission JSON from:

```
output/{mission_id}.json
```

The current package layout is:

```
src/
+-- tars/
    +-- phase1/
        |-- mission_runner.py
        |-- telemetry_collector.py
        |-- fault_injector.py
        +-- models/
            +-- telemetry.py
```

Phase 2 should preserve that package direction and add:

```
src/
+-- tars/
    +-- phase2/
        |-- __init__.py
        |-- api.py
        |-- config.py
        |-- database.py
        |-- importer.py
        |-- replay.py
        |-- service.py
        +-- models/
            |-- __init__.py
            |-- db.py
            +-- schemas.py
```

The Phase 1 `MissionTelemetry` Pydantic model remains the canonical input contract for imports. Phase 2 should validate all imported JSON through that model before writing to the database.

---

## Architecture Overview

```mermaid
flowchart LR
    A[Phase 1 Mission JSON] --> B[Importer]
    B --> C[(PostgreSQL)]
    D[FastAPI] --> C
    D --> E[Mission Query API]
    D --> F[Replay API]
    F --> G[Ordered Telemetry Frames]
    G --> H[Phase 3 State Engine Input]
```

### Components

| Component | Responsibility |
|-----------|----------------|
| **Importer** | Load Phase 1 JSON files, validate them, and persist missions/events/faults. |
| **PostgreSQL** | Durable mission store. Keeps full telemetry history queryable and replayable. |
| **FastAPI** | Exposes mission listing, mission detail, event query, and replay endpoints. |
| **Replay Service** | Converts stored telemetry rows into ordered replay frames with timing metadata. |
| **Schemas** | Pydantic request/response models for the API boundary. |

---

## Data Model

Use relational tables for queryable metadata and JSONB for nested telemetry payloads. This keeps Phase 2 simple while still allowing future analysis queries.

### `missions`

| Column | Type | Notes |
|--------|------|-------|
| `id` | UUID or BIGSERIAL | Internal database id. |
| `mission_id` | TEXT UNIQUE | Phase 1 mission id, e.g. `mission_20260608_120000`. |
| `drone_id` | TEXT | From Phase 1 output. |
| `start_time` | TIMESTAMPTZ | Mission start. |
| `end_time` | TIMESTAMPTZ NULL | Mission end. |
| `mission_result` | TEXT | `SUCCESS`, `FAILURE`, `ABORTED`, `IN_PROGRESS`. |
| `summary` | JSONB | Phase 1 mission summary. |
| `source_file` | TEXT NULL | Path imported from. |
| `created_at` | TIMESTAMPTZ | Insert timestamp. |

### `telemetry_events`

| Column | Type | Notes |
|--------|------|-------|
| `id` | BIGSERIAL | Event id. |
| `mission_id` | TEXT FK | References `missions.mission_id`. |
| `sequence` | INTEGER | Zero-based event order in mission. |
| `timestamp` | TIMESTAMPTZ | Snapshot timestamp. |
| `elapsed_ms` | INTEGER | Milliseconds from mission start. |
| `position` | JSONB NULL | Position payload. |
| `velocity` | JSONB NULL | Velocity payload. |
| `battery` | JSONB NULL | Battery payload. |
| `gps` | JSONB NULL | GPS payload. |
| `attitude` | JSONB NULL | Attitude payload. |
| `flight_mode` | TEXT NULL | Current flight mode. |
| `health` | JSONB NULL | Health payload. |
| `raw` | JSONB | Full original snapshot for forward compatibility. |

Indexes:

- `(mission_id, sequence)`
- `(mission_id, timestamp)`
- `(timestamp)`
- GIN index on `raw` only if JSONB filtering becomes necessary.

### `fault_events`

| Column | Type | Notes |
|--------|------|-------|
| `id` | BIGSERIAL | Fault event id. |
| `mission_id` | TEXT FK | References `missions.mission_id`. |
| `fault_type` | TEXT | `gps_block`, `wind_gust`, etc. |
| `triggered_at` | TIMESTAMPTZ | Fault timestamp. |
| `elapsed_ms` | INTEGER NULL | Milliseconds from mission start. |
| `parameters` | JSONB | Fault parameters. |
| `description` | TEXT | Human-readable description. |

Indexes:

- `(mission_id, triggered_at)`
- `(mission_id, fault_type)`

---

## API Contract

Base path:

```
/api/v1
```

### Health

`GET /health`

Returns API and database readiness.

```json
{
  "status": "ok",
  "database": "ok"
}
```

### Import Mission

`POST /missions/import`

Imports one existing Phase 1 JSON file by local path.

Request:

```json
{
  "path": "output/mission_20260608_120000.json",
  "overwrite": false
}
```

Response:

```json
{
  "mission_id": "mission_20260608_120000",
  "events_imported": 342,
  "faults_imported": 2,
  "status": "imported"
}
```

### List Missions

`GET /missions?limit=50&offset=0&result=SUCCESS&drone_id=tars-sim-01`

Returns mission summaries only, not full telemetry.

### Get Mission

`GET /missions/{mission_id}`

Returns metadata, summary, and faults.

### Get Mission Events

`GET /missions/{mission_id}/events?limit=1000&offset=0`

Returns raw ordered telemetry snapshots from the database.

### Replay Mission

`GET /missions/{mission_id}/replay?speed=1.0&from_ms=0&to_ms=60000`

Returns ordered replay frames with elapsed timing. Phase 2 can start with a JSON response rather than server-sent events or WebSockets.

```json
{
  "mission_id": "mission_20260608_120000",
  "speed": 1.0,
  "frames": [
    {
      "sequence": 0,
      "elapsed_ms": 0,
      "timestamp": "2026-06-08T06:30:00Z",
      "telemetry": {}
    }
  ]
}
```

Optional stretch endpoint:

`GET /missions/{mission_id}/replay/stream`

Streams replay frames with server-sent events. Build this only after the basic JSON replay endpoint works.

---

## Implementation Plan

### Step 1: Add Phase 2 Dependencies

Update `requirements.txt` with:

```
fastapi>=0.115.0
uvicorn[standard]>=0.30.0
sqlalchemy>=2.0.0
asyncpg>=0.29.0
alembic>=1.13.0
```

Keep the existing Phase 1 dependencies.

### Step 2: Add PostgreSQL Service

Extend `docker/docker-compose.yml` with a `postgres` service.

Recommended local defaults:

```
POSTGRES_DB=tars
POSTGRES_USER=tars
POSTGRES_PASSWORD=tars
```

Expose port `5432` to the host. Keep PX4 SITL separate; Phase 2 should be runnable without starting PX4/Gazebo.

Add `.env.example` values:

```
DATABASE_URL=postgresql+asyncpg://tars:tars@localhost:5432/tars
API_HOST=0.0.0.0
API_PORT=8000
```

### Step 3: Create Phase 2 Package

Create:

```
src/tars/phase2/__init__.py
src/tars/phase2/config.py
src/tars/phase2/database.py
src/tars/phase2/models/db.py
src/tars/phase2/models/schemas.py
src/tars/phase2/importer.py
src/tars/phase2/replay.py
src/tars/phase2/service.py
src/tars/phase2/api.py
```

Responsibilities:

- `config.py`: environment settings.
- `database.py`: async SQLAlchemy engine/session setup.
- `models/db.py`: ORM tables.
- `models/schemas.py`: API request/response schemas.
- `importer.py`: validate and ingest Phase 1 JSON.
- `replay.py`: construct replay frames from stored events.
- `service.py`: mission query/import orchestration.
- `api.py`: FastAPI app and routes.

### Step 4: Add Migrations

Initialize Alembic and create the first migration:

```
alembic init migrations
alembic revision --autogenerate -m "create phase 2 mission replay tables"
alembic upgrade head
```

Tables:

- `missions`
- `telemetry_events`
- `fault_events`

### Step 5: Implement Import Flow

Importer behavior:

1. Accept a JSON file path.
2. Load the file.
3. Validate with `tars.phase1.models.telemetry.MissionTelemetry`.
4. Insert one `missions` row.
5. Insert one `telemetry_events` row per snapshot.
6. Insert one `fault_events` row per fault.
7. Reject duplicate `mission_id` unless `overwrite=true`.

Important details:

- Preserve original snapshot JSON in `telemetry_events.raw`.
- Compute `sequence` from the telemetry array order.
- Compute `elapsed_ms` from `snapshot.timestamp - mission.start_time`.
- Keep import idempotent for repeated local development.

### Step 6: Implement Query API

Build these endpoints first:

```
GET  /api/v1/health
POST /api/v1/missions/import
GET  /api/v1/missions
GET  /api/v1/missions/{mission_id}
GET  /api/v1/missions/{mission_id}/events
GET  /api/v1/missions/{mission_id}/replay
```

Keep responses small by default. Listing missions should not include full telemetry arrays.

### Step 7: Add CLI Scripts

Add:

```
scripts/start_replay_api.sh
scripts/import_mission.sh
```

Expected commands:

```
./scripts/start_replay_api.sh
./scripts/import_mission.sh output/mission_20260608_120000.json
```

The API script should run:

```
PYTHONPATH=src .venv/bin/uvicorn tars.phase2.api:app --host 0.0.0.0 --port 8000
```

### Step 8: Add Tests

Create focused tests around deterministic replay behavior:

```
tests/phase2/test_importer.py
tests/phase2/test_replay.py
tests/phase2/test_api.py
```

Minimum coverage:

- Valid Phase 1 JSON imports successfully.
- Duplicate import is rejected unless overwrite is enabled.
- Events are returned in sequence order.
- Replay frames include `elapsed_ms`.
- Fault events are persisted and returned with mission detail.

### Step 9: Update Docs

Update README with a Phase 2 section after Phase 1:

```
## Phase 2 -- Mission Replay System
```

Include:

- Start PostgreSQL.
- Run migrations.
- Start API.
- Import a mission JSON.
- List missions.
- Replay a mission.

---

## Definition of Done

Phase 2 is complete when:

1. PostgreSQL runs locally through Docker Compose.
2. The API starts with `PYTHONPATH=src .venv/bin/uvicorn tars.phase2.api:app`.
3. A Phase 1 mission JSON can be imported into PostgreSQL.
4. Re-importing the same mission is deterministic and controlled by `overwrite`.
5. `GET /api/v1/missions` lists imported missions.
6. `GET /api/v1/missions/{mission_id}` returns metadata, summary, and faults.
7. `GET /api/v1/missions/{mission_id}/events` returns ordered telemetry.
8. `GET /api/v1/missions/{mission_id}/replay` returns ordered replay frames with elapsed timing.
9. Tests cover importer, replay ordering, and core API routes.
10. Phase 3 can consume replay frames without reading Phase 1 JSON directly.

---

## Explicit Non-Goals

Do not build these in Phase 2:

- Redis operational state store.
- Incident detection or anomaly scoring.
- Gemini or any LLM calls.
- Phoenix tracing.
- Neo4j graph memory.
- Kafka/event bus.
- Real-time drone control through the API.
- Web dashboard.

The only job is to make missions durable, queryable, and replayable.

---

## Why This Phase Matters

Phase 1 proves telemetry exists.

Phase 2 makes telemetry reusable.

After this phase, every later layer can be built and tested against stored missions instead of needing PX4/Gazebo running every time. That is the hinge: replay turns one successful simulation run into a permanent development asset.
