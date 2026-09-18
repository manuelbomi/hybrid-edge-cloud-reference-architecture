"""
End-to-end test: local API -> store-and-forward queue -> cloud ingest API.

Unlike test_forwarder.py (which uses a scripted mock endpoint) and
test_ingest_api.py (which tests the cloud API in isolation), this test wires
the *real* cloud FastAPI app in as the Forwarder's HTTP target, using
httpx's ASGI transport (an in-process call, no real network/sockets
involved). It proves the whole pipeline actually agrees on the wire format,
not just that each half works against a mock of the other.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from cloud.ingest_api import create_app as create_ingest_app
from edge.forwarder import STATUS_DELIVERED, Forwarder
from edge.local_api import create_app as create_local_app
from tests.conftest import FakeClock


@pytest.mark.asyncio
async def test_events_flow_from_local_api_through_forwarder_to_cloud_ingest(tmp_path: Path):
    # Cloud side: a real ingest API, backed by its own temp SQLite file.
    ingest_app = create_ingest_app(str(tmp_path / "cloud_ingest.db"))

    # The Forwarder talks to that real app in-process via ASGI transport --
    # this is a real HTTP request/response cycle, just without real sockets.
    asgi_client = httpx.AsyncClient(transport=httpx.ASGITransport(app=ingest_app), base_url="http://cloud.test")

    clock = FakeClock()
    forwarder = Forwarder(
        db_path=str(tmp_path / "edge_queue.db"),
        cloud_endpoint="/ingest",
        http_client=asgi_client,
        clock=clock,
        poll_interval_seconds=0.01,
    )

    # Edge side: the real local API, using that same forwarder.
    local_app = create_local_app(forwarder, run_background_loop=False)
    local_transport = httpx.ASGITransport(app=local_app)
    local_client = httpx.AsyncClient(transport=local_transport, base_url="http://edge.test")

    response = await local_client.post(
        "/events",
        json={"source": "camera-01", "event_type": "person_detected", "data": {"confidence": 0.95}},
    )
    assert response.status_code == 202
    event_id = response.json()["event_id"]

    # Nothing has reached the cloud yet -- it's only in the local queue so far.
    ingest_transport = httpx.ASGITransport(app=ingest_app)
    ingest_client = httpx.AsyncClient(transport=ingest_transport, base_url="http://cloud.test")
    assert (await ingest_client.get("/events")).json() == []

    # Run one delivery pass explicitly (this is what the forwarder's
    # background loop does continuously in docker-compose.edge.yml).
    summary = await forwarder.deliver_pending()
    assert summary == {"attempted": 1, "delivered": 1, "failed": 0}
    assert forwarder.get_event(event_id).status == STATUS_DELIVERED

    # The cloud now has it.
    cloud_events = (await ingest_client.get("/events")).json()
    assert len(cloud_events) == 1
    assert cloud_events[0]["source"] == "camera-01"
    assert cloud_events[0]["event_type"] == "person_detected"
    assert cloud_events[0]["data"] == {"confidence": 0.95}

    await asgi_client.aclose()
    await local_client.aclose()
    await ingest_client.aclose()
