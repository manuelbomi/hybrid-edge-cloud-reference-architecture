# ADR-002: MQTT at the edge, HTTPS to the cloud

## Status

Accepted

## Context

An edge site typically has several local producers of events -- cameras,
sensors, an NVR, maybe a simulated event generator in this demo -- and one
or more consumers that need those events (the local API, the forwarder, any
local automation). Separately, that site needs to get events to a cloud
ingestion endpoint over the WAN. These are two different networking problems
with different constraints, and we chose a different protocol for each.

**Locally**, devices are on the same LAN, connections are cheap, and we
often want a "fire and forget, many subscribers" pattern (a camera event
might matter to the local API, to a local dashboard, and to a local alerting
rule, all at once). We need something lightweight enough to run on modest
edge hardware alongside everything else.

**Across the WAN**, we are talking to a single, well-known endpoint
(the cloud ingestion API), we need the request to survive typical corporate
network security policy (proxies, firewalls that only allow standard web
ports), and we need transport security and delivery semantics we can reason
about (2xx means accepted, non-2xx or a timeout means retry).

## Decision

- **Locally, use MQTT** (via an `eclipse-mosquitto` broker in
  `docker-compose.edge.yml`) as the local pub/sub bus. Producers like
  `edge/mock_camera_generator.py` publish to a topic; `edge/local_api.py`
  subscribes and bridges messages into the durable queue.
- **Edge-to-cloud, use HTTPS** as the transport the `Forwarder`
  (`edge/forwarder.py`) uses to deliver queued events to the cloud
  ingestion API (`cloud/ingest_api.py`).

## Consequences

- **MQTT gives us cheap local fan-out** without every consumer needing to
  know about every producer, and it is a natural fit for constrained edge
  devices (small footprint, simple pub/sub semantics, widely supported by
  camera/sensor vendors already).
- **HTTPS to the cloud is boring in the best way.** It works through
  standard corporate firewalls and proxies that already allow outbound
  web traffic, gets us TLS for free, has unambiguous request/response
  semantics that map directly onto the Forwarder's "2xx = delivered,
  otherwise retry" logic, and is trivial to put behind a standard load
  balancer or API gateway on the cloud side (see `infra/terraform/`).
- **We do not run MQTT across the WAN.** It would be possible to have the
  edge broker bridge directly to a cloud MQTT broker, but that pushes
  connection-state management (reconnect/backoff/session persistence)
  into the broker layer, outside of our own retry/backoff/TTL logic, and
  makes the cloud side depend on operating a broker instead of a simple
  stateless HTTP API. Keeping the edge-to-cloud hop as plain HTTPS calls
  driven by our own `Forwarder` keeps that logic visible, testable (see
  `tests/test_forwarder.py`), and easy to reason about.
- **The local demo uses unauthenticated MQTT** (`allow_anonymous true` in
  `edge/mosquitto.conf`) for simplicity. A real deployment should add
  broker authentication and TLS for the local MQTT traffic too; see the
  README's hardening notes.
