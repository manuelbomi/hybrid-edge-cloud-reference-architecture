"""
edge/local_api.py

Tiny local HTTP front door for an edge site.

This is what a camera bridge, an MQTT-to-HTTP adapter, or a simple
polling script talks to. Its jobs are:

1. Accept an event (as JSON) over HTTP at ``POST /events``.
2. Optionally bridge events published to a local MQTT broker (e.g. by
   ``edge/mock_camera_generator.py``) into the same queue.
3. Hand every accepted event to the store-and-forward queue
   (``edge.forwarder.Forwarder``) so it survives a WAN outage, a
   container restart, etc.

This app intentionally does *not* try to deliver events to the cloud
itself. That job belongs to the Forwarder's background loop, which in
``docker-compose.edge.yml`` runs as its own container/process sharing
the same SQLite queue file. For simpler single-process use (e.g. local
development) this app can also run the delivery loop in-process by
setting ``RUN_FORWARDER_LOOP=true``.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from contextlib import asynccontextmanager
from typing import Any, Optional

from fastapi import FastAPI
from pydantic import BaseModel, Field

from edge.forwarder import Forwarder

logger = logging.getLogger("edge.local_api")


class EventIn(BaseModel):
    """A single event coming from a camera, sensor, or MQTT bridge."""

    source: str = Field(..., description="Where the event came from, e.g. a camera id")
    event_type: str = Field(..., description="e.g. 'motion_detected', 'person_detected'")
    data: dict[str, Any] = Field(default_factory=dict)
    timestamp: Optional[float] = Field(default=None, description="Unix time; server fills in if omitted")


def build_forwarder_from_env() -> Forwarder:
    """Build a Forwarder configured from environment variables.

    Kept separate from ``create_app`` so tests can build their own
    ``Forwarder`` (pointed at a temp DB and a mock HTTP client) and pass
    it into ``create_app`` directly instead of relying on env vars.
    """
    db_path = os.environ.get("FORWARDER_DB_PATH", "./data/edge_queue.db")
    cloud_endpoint = os.environ.get("CLOUD_INGEST_URL", "http://localhost:8080/ingest")
    return Forwarder(
        db_path=db_path,
        cloud_endpoint=cloud_endpoint,
        base_backoff_seconds=float(os.environ.get("BASE_BACKOFF_SECONDS", "1.0")),
        max_backoff_seconds=float(os.environ.get("MAX_BACKOFF_SECONDS", "300.0")),
        ttl_seconds=float(os.environ.get("TTL_SECONDS", str(24 * 60 * 60))),
        poll_interval_seconds=float(os.environ.get("POLL_INTERVAL_SECONDS", "2.0")),
    )


def handle_mqtt_message(forwarder: Forwarder, raw_payload: bytes) -> Optional[int]:
    """Decode one MQTT message body and enqueue it.

    Pulled out as a standalone function (instead of an inline closure)
    so it can be unit tested without a real MQTT broker -- see
    ``tests/test_mqtt_bridge.py``.

    Returns the queued event's row id, or ``None`` if the payload was
    not valid JSON (the message is logged and dropped rather than
    crashing the bridge).
    """
    try:
        payload = json.loads(raw_payload.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        logger.warning("dropping non-JSON MQTT message (%d bytes)", len(raw_payload))
        return None
    return forwarder.enqueue(payload)


def _maybe_start_mqtt_bridge(forwarder: Forwarder) -> Optional[threading.Thread]:
    """Start a background MQTT subscriber thread if MQTT_BROKER_HOST is set.

    This is a best-effort bridge: a simulated camera fleet
    (``edge/mock_camera_generator.py``) publishes JSON events to a topic
    on the local Mosquitto broker, and this subscriber forwards each one
    into the same durable queue that ``POST /events`` writes to. If no
    broker host is configured (e.g. when running unit tests, or when
    only HTTP ingestion is used), this is a no-op.
    """
    host = os.environ.get("MQTT_BROKER_HOST")
    if not host:
        return None

    try:
        import paho.mqtt.client as mqtt
    except ImportError:
        logger.warning("paho-mqtt not installed; skipping MQTT bridge")
        return None

    port = int(os.environ.get("MQTT_BROKER_PORT", "1883"))
    topic = os.environ.get("MQTT_TOPIC", "cameras/events")

    def on_message(_client: Any, _userdata: Any, msg: Any) -> None:
        handle_mqtt_message(forwarder, msg.payload)

    def _connect_and_loop() -> None:
        client = mqtt.Client()
        client.on_message = on_message
        while True:
            try:
                client.connect(host, port, keepalive=30)
                client.subscribe(topic)
                logger.info("MQTT bridge connected to %s:%s topic=%s", host, port, topic)
                client.loop_forever()
            except Exception:  # noqa: BLE001 - keep retrying, this runs forever
                logger.warning("MQTT bridge lost connection to %s:%s, retrying", host, port)
                time.sleep(5)

    thread = threading.Thread(target=_connect_and_loop, daemon=True, name="mqtt-bridge")
    thread.start()
    return thread


def create_app(forwarder: Forwarder, *, run_background_loop: bool = False, enable_mqtt_bridge: bool = False) -> FastAPI:
    """Build the FastAPI app around a given Forwarder instance.

    Taking the ``Forwarder`` as a parameter (rather than constructing it
    at import time) is what makes this app easy to test: tests build a
    ``Forwarder`` against a temp SQLite file, wrap it in
    ``create_app(...)``, and drive it with FastAPI's ``TestClient``.
    """

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        if run_background_loop:
            forwarder.start()
        if enable_mqtt_bridge:
            _maybe_start_mqtt_bridge(forwarder)
        yield
        if run_background_loop:
            await forwarder.stop()

    app = FastAPI(title="Edge Local API", lifespan=lifespan)
    app.state.forwarder = forwarder

    @app.post("/events", status_code=202)
    def post_event(event: EventIn) -> dict:
        payload = event.model_dump()
        if payload.get("timestamp") is None:
            payload["timestamp"] = time.time()
        event_id = forwarder.enqueue(payload)
        return {"queued": True, "event_id": event_id}

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "queue_counts": forwarder.counts()}

    return app


# Default app instance for `uvicorn edge.local_api:app`.
app = create_app(
    build_forwarder_from_env(),
    run_background_loop=os.environ.get("RUN_FORWARDER_LOOP", "false").lower() == "true",
    enable_mqtt_bridge=os.environ.get("MQTT_BROKER_HOST") is not None,
)
