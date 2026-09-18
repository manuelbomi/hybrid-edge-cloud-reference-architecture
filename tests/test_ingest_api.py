"""Tests for cloud/ingest_api.py -- the cloud-side ingestion endpoint."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from cloud.ingest_api import create_app


def make_client(tmp_path: Path) -> TestClient:
    db_path = str(tmp_path / "cloud_ingest.db")
    app = create_app(db_path)
    return TestClient(app)


def test_ingest_accepts_and_stores_a_valid_event(tmp_path):
    client = make_client(tmp_path)

    response = client.post(
        "/ingest",
        json={
            "source": "camera-01",
            "event_type": "person_detected",
            "data": {"confidence": 0.92, "zone": "entrance"},
            "timestamp": 1_700_000_000.0,
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["stored"] is True
    assert isinstance(body["id"], int)

    listed = client.get("/events").json()
    assert len(listed) == 1
    stored = listed[0]
    assert stored["source"] == "camera-01"
    assert stored["event_type"] == "person_detected"
    assert stored["data"] == {"confidence": 0.92, "zone": "entrance"}
    assert stored["event_timestamp"] == 1_700_000_000.0


def test_events_endpoint_orders_most_recent_first_and_respects_limit(tmp_path):
    client = make_client(tmp_path)

    for i in range(5):
        client.post(
            "/ingest",
            json={"source": f"camera-{i:02d}", "event_type": "motion_detected", "data": {}},
        )

    listed = client.get("/events", params={"limit": 2}).json()
    assert len(listed) == 2
    # Most recently inserted (camera-04) should come first.
    assert listed[0]["source"] == "camera-04"
    assert listed[1]["source"] == "camera-03"


def test_health_endpoint(tmp_path):
    client = make_client(tmp_path)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
