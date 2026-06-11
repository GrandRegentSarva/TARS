"""
API Tests
=========
Tests for the Phase 2 FastAPI endpoints.

Coverage:
- Health endpoint returns ok
- Import endpoint accepts valid mission JSON
- Import endpoint rejects duplicates (409)
- List missions returns imported missions
- Get mission returns metadata and faults
- Get mission events returns ordered telemetry
- Replay endpoint returns ordered frames with elapsed_ms
- 404 for non-existent missions
"""

from __future__ import annotations

import json
import os
import tempfile

import pytest

from .conftest import make_sample_mission


pytestmark = pytest.mark.asyncio


def _write_mission_file(data: dict) -> str:
    """Write mission data to a temp file and return the path."""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, dir="."
    ) as f:
        json.dump(data, f)
        return f.name


async def test_health(client):
    """GET /health returns status ok."""
    resp = await client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["database"] == "ok"


async def test_import_mission(client):
    """POST /api/v1/missions/import imports a valid mission."""
    data = make_sample_mission()
    path = _write_mission_file(data)

    resp = await client.post(
        "/api/v1/missions/import",
        json={"path": path, "overwrite": False},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["mission_id"] == "test_mission_001"
    assert body["events_imported"] == 5
    assert body["faults_imported"] == 1
    assert body["status"] == "imported"

    os.unlink(path)


async def test_import_duplicate_rejected(client):
    """POST /api/v1/missions/import rejects duplicate mission_id with 409."""
    data = make_sample_mission()
    path = _write_mission_file(data)

    # First import
    resp1 = await client.post(
        "/api/v1/missions/import",
        json={"path": path, "overwrite": False},
    )
    assert resp1.status_code == 200

    # Second import -- should be rejected
    resp2 = await client.post(
        "/api/v1/missions/import",
        json={"path": path, "overwrite": False},
    )
    assert resp2.status_code == 409

    os.unlink(path)


async def test_import_duplicate_with_overwrite(client):
    """POST /api/v1/missions/import with overwrite=true replaces existing."""
    data = make_sample_mission()
    path = _write_mission_file(data)

    # First import
    resp1 = await client.post(
        "/api/v1/missions/import",
        json={"path": path, "overwrite": False},
    )
    assert resp1.status_code == 200

    # Second import with overwrite
    resp2 = await client.post(
        "/api/v1/missions/import",
        json={"path": path, "overwrite": True},
    )
    assert resp2.status_code == 200

    os.unlink(path)


async def test_import_missing_file(client):
    """POST /api/v1/missions/import returns 400 for missing file."""
    resp = await client.post(
        "/api/v1/missions/import",
        json={"path": "nonexistent.json", "overwrite": False},
    )
    assert resp.status_code == 400


async def test_list_missions(client):
    """GET /api/v1/missions returns imported missions."""
    data = make_sample_mission()
    path = _write_mission_file(data)

    await client.post(
        "/api/v1/missions/import",
        json={"path": path, "overwrite": False},
    )

    resp = await client.get("/api/v1/missions")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert len(body["missions"]) == 1
    assert body["missions"][0]["mission_id"] == "test_mission_001"
    assert body["missions"][0]["mission_result"] == "SUCCESS"

    os.unlink(path)


async def test_list_missions_filter_by_result(client):
    """GET /api/v1/missions?result=FAILURE returns empty when no failures."""
    data = make_sample_mission()
    path = _write_mission_file(data)

    await client.post(
        "/api/v1/missions/import",
        json={"path": path, "overwrite": False},
    )

    resp = await client.get("/api/v1/missions?result=FAILURE")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 0

    os.unlink(path)


async def test_get_mission(client):
    """GET /api/v1/missions/{mission_id} returns metadata and faults."""
    data = make_sample_mission()
    path = _write_mission_file(data)

    await client.post(
        "/api/v1/missions/import",
        json={"path": path, "overwrite": False},
    )

    resp = await client.get("/api/v1/missions/test_mission_001")
    assert resp.status_code == 200
    body = resp.json()
    assert body["mission_id"] == "test_mission_001"
    assert body["drone_id"] == "tars-sim-01"
    assert body["mission_result"] == "SUCCESS"
    assert len(body["faults"]) == 1
    assert body["faults"][0]["fault_type"] == "gps_block"

    os.unlink(path)


async def test_get_mission_not_found(client):
    """GET /api/v1/missions/{mission_id} returns 404 for unknown mission."""
    resp = await client.get("/api/v1/missions/nonexistent")
    assert resp.status_code == 404


async def test_get_mission_events(client):
    """GET /api/v1/missions/{mission_id}/events returns ordered telemetry."""
    data = make_sample_mission(num_snapshots=5)
    path = _write_mission_file(data)

    await client.post(
        "/api/v1/missions/import",
        json={"path": path, "overwrite": False},
    )

    resp = await client.get("/api/v1/missions/test_mission_001/events")
    assert resp.status_code == 200
    body = resp.json()
    assert body["mission_id"] == "test_mission_001"
    assert body["total"] == 5
    assert len(body["events"]) == 5

    # Verify sequence ordering
    for i, event in enumerate(body["events"]):
        assert event["sequence"] == i

    os.unlink(path)


async def test_get_mission_events_not_found(client):
    """GET /api/v1/missions/{mission_id}/events returns 404 for unknown."""
    resp = await client.get("/api/v1/missions/nonexistent/events")
    assert resp.status_code == 404


async def test_replay_mission(client):
    """GET /api/v1/missions/{mission_id}/replay returns ordered frames."""
    data = make_sample_mission(num_snapshots=5)
    path = _write_mission_file(data)

    await client.post(
        "/api/v1/missions/import",
        json={"path": path, "overwrite": False},
    )

    resp = await client.get("/api/v1/missions/test_mission_001/replay")
    assert resp.status_code == 200
    body = resp.json()
    assert body["mission_id"] == "test_mission_001"
    assert body["total_frames"] == 5

    # Verify frames are ordered with elapsed_ms
    for i, frame in enumerate(body["frames"]):
        assert frame["sequence"] == i
        assert frame["elapsed_ms"] == i * 1000
        assert "telemetry" in frame

    os.unlink(path)


async def test_replay_with_time_range(client):
    """GET /api/v1/missions/{mission_id}/replay with from_ms and to_ms."""
    data = make_sample_mission(num_snapshots=10)
    path = _write_mission_file(data)

    await client.post(
        "/api/v1/missions/import",
        json={"path": path, "overwrite": False},
    )

    resp = await client.get(
        "/api/v1/missions/test_mission_001/replay?from_ms=2000&to_ms=5000"
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_frames"] == 4  # 2000, 3000, 4000, 5000
    assert body["frames"][0]["elapsed_ms"] == 2000
    assert body["frames"][-1]["elapsed_ms"] == 5000

    os.unlink(path)


async def test_replay_not_found(client):
    """GET /api/v1/missions/{mission_id}/replay returns 404 for unknown."""
    resp = await client.get("/api/v1/missions/nonexistent/replay")
    assert resp.status_code == 404
