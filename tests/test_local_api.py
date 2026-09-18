"""Tests for edge/local_api.py -- the local HTTP front door at an edge site."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from edge.forwarder import Forwarder
from edge.local_api import create_app


def make_client(tmp_path: Path) -> TestClient:
    db_path = str(tmp_path / "edge_queue.db")
    # Point at a dummy endpoint; these tests only exercise enqueueing via the
    # HTTP layer, not delivery, so no real/mock network client is needed.
    forwarder = Forwarder(db_path=db_path, cloud_endpoint="http://cloud.test/ingest")
    app = create_app(forwarder, run_background_loop=False)
    return TestClient(app)


def test_post_events_queues_event_and_returns_id(tmp_path):
    client = make_client(tmp_path)

    response = client.post(
        "/events",
        json={"source": "camera-01", "event_type": "motion_detected", "data": {"confidence": 0.8}},
    )

    assert response.status_code == 202
    body = response.json()
    assert body["queued"] is True
    assert isinstance(body["event_id"], int)


def test_post_events_fills_in_timestamp_when_omitted(tmp_path):
    client = make_client(tmp_path)
    forwarder: Forwarder = client.app.state.forwarder

    response = client.post("/events", json={"source": "camera-02", "event_type": "no_event"})
    event_id = response.json()["event_id"]

    stored = forwarder.get_event(event_id)
    assert stored is not None
    assert stored.payload["timestamp"] is not None


def test_health_reports_queue_counts(tmp_path):
    client = make_client(tmp_path)
    client.post("/events", json={"source": "camera-01", "event_type": "motion_detected"})

    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["queue_counts"] == {"pending": 1}
