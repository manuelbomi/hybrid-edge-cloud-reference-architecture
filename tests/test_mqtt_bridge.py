"""
Tests for the MQTT -> queue bridging logic in edge/local_api.py.

These test the message-handling function directly rather than spinning up a
real Mosquitto broker, so they run fast and don't need Docker. The bridge's
*connection* handling (edge/local_api.py's `_maybe_start_mqtt_bridge`) is
exercised manually via docker-compose.edge.yml instead -- see README.md.
"""

from __future__ import annotations

from pathlib import Path

from edge.forwarder import Forwarder
from edge.local_api import handle_mqtt_message


def make_forwarder(tmp_path: Path) -> Forwarder:
    db_path = str(tmp_path / "edge_queue.db")
    return Forwarder(db_path=db_path, cloud_endpoint="http://cloud.test/ingest")


def test_handle_mqtt_message_enqueues_valid_json(tmp_path):
    forwarder = make_forwarder(tmp_path)
    raw = b'{"source": "camera-03", "event_type": "vehicle_detected", "data": {"zone": "parking_lot"}}'

    event_id = handle_mqtt_message(forwarder, raw)

    assert event_id is not None
    stored = forwarder.get_event(event_id)
    assert stored is not None
    assert stored.payload["source"] == "camera-03"
    assert stored.payload["event_type"] == "vehicle_detected"


def test_handle_mqtt_message_drops_invalid_json(tmp_path):
    forwarder = make_forwarder(tmp_path)
    raw = b"not valid json {{{"

    event_id = handle_mqtt_message(forwarder, raw)

    assert event_id is None
    assert forwarder.counts() == {}
