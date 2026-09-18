"""
edge/mock_camera_generator.py

Simulates a small fleet of AI cameras at an edge site by publishing
fake detection events to the local MQTT broker on a fixed interval.

This is only used for the local demo / ``docker-compose.edge.yml``. A
real deployment would replace this script with actual cameras, an NVR
with an MQTT export feature, or a proper camera-to-MQTT bridge -- the
rest of the stack (broker, local API, forwarder) does not care where
the events came from.
"""

from __future__ import annotations

import json
import os
import random
import time

import paho.mqtt.client as mqtt

BROKER_HOST = os.environ.get("MQTT_BROKER_HOST", "mosquitto")
BROKER_PORT = int(os.environ.get("MQTT_BROKER_PORT", "1883"))
TOPIC = os.environ.get("MQTT_TOPIC", "cameras/events")
CAMERA_COUNT = int(os.environ.get("MOCK_CAMERA_COUNT", "3"))
INTERVAL_SECONDS = float(os.environ.get("MOCK_EVENT_INTERVAL_SECONDS", "5.0"))

EVENT_TYPES = ["motion_detected", "person_detected", "vehicle_detected", "no_event"]
ZONES = ["entrance", "loading_dock", "parking_lot", "warehouse_floor"]


def build_event(camera_id: str) -> dict:
    """Build one fake camera detection event."""
    return {
        "source": camera_id,
        "event_type": random.choice(EVENT_TYPES),
        "data": {
            "confidence": round(random.uniform(0.5, 0.99), 2),
            "zone": random.choice(ZONES),
        },
        "timestamp": time.time(),
    }


def connect_with_retry(client: mqtt.Client, host: str, port: int) -> None:
    while True:
        try:
            client.connect(host, port, keepalive=30)
            return
        except (OSError, ConnectionRefusedError) as exc:
            print(f"could not reach broker at {host}:{port} ({exc}); retrying in 3s")
            time.sleep(3)


def main() -> None:
    client = mqtt.Client()
    connect_with_retry(client, BROKER_HOST, BROKER_PORT)
    client.loop_start()

    cameras = [f"camera-{i:02d}" for i in range(1, CAMERA_COUNT + 1)]
    print(f"mock camera generator publishing {len(cameras)} camera(s) to {BROKER_HOST}:{BROKER_PORT} topic={TOPIC}")

    try:
        while True:
            for camera_id in cameras:
                event = build_event(camera_id)
                client.publish(TOPIC, json.dumps(event))
            time.sleep(INTERVAL_SECONDS)
    except KeyboardInterrupt:
        pass
    finally:
        client.loop_stop()
        client.disconnect()


if __name__ == "__main__":
    main()
