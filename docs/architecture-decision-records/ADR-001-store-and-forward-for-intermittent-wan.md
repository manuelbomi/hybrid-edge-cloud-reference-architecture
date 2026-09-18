# ADR-001: Store-and-forward for intermittent WAN links

## Status

Accepted

## Context

Edge sites in this architecture connect to the cloud over WAN links that are
not always reliable -- think a retail store on a shared broadband connection,
a warehouse on a cellular failover link, or a remote site with scheduled
maintenance windows on its primary circuit. Events generated at the edge
(camera detections, sensor readings) need to eventually reach the cloud for
storage and analytics, but "eventually" is the operative word: requiring an
immediate, successful network call for every event is not realistic given
the link quality we have to design for.

We considered three options for how the edge should handle an event when the
cloud is unreachable:

1. **Drop the event** and move on.
2. **Block and retry synchronously** until the cloud accepts it, before doing
   anything else.
3. **Store the event locally and forward it asynchronously** in the
   background, independent of whatever produced the event.

## Decision

We chose option 3: store-and-forward. Every accepted event is written to a
local, durable SQLite queue immediately, before any attempt is made to
deliver it. A background loop then delivers pending events to the cloud with
retry and exponential backoff, marks them delivered on success, and purges
them from the local queue once delivered (or once they exceed a configured
retention window without being delivered).

This is implemented in `edge/forwarder.py` (the `Forwarder` class) and is the
most heavily tested part of this repository (see `tests/test_forwarder.py`).

## Consequences

- **Producers of events never block on the network.** `edge/local_api.py`'s
  `POST /events` returns as soon as the event is on disk, regardless of
  whether the cloud is reachable at that moment.
- **No data loss during ordinary, bounded outages.** Events queue up locally
  and flush to the cloud, in order, once the link recovers.
- **Data loss is still possible, by design, for very long outages.** The TTL
  (`ttl_seconds`) is a deliberate trade-off: unlimited local retention could
  fill up edge storage during an extended outage, so events older than the
  configured window are purged even if never delivered. Operators need to
  pick a TTL that matches how much local disk they have and how much data
  loss is acceptable for a worst-case outage.
- **The cloud must tolerate at-least-once delivery.** Because a delivery can
  succeed on the cloud side but the acknowledgment can be lost in transit
  (rare, but possible), the cloud ingestion endpoint should be written to
  treat duplicate events as harmless, or the events themselves should carry
  an id that allows deduplication downstream. This demo does not implement
  deduplication; production hardening notes in the README call this out.
- **Local storage needs to be durable and, ideally, encrypted.** SQLite is
  used here because it is simple, requires no extra service, and gives us
  transactional writes for free. See the README's hardening notes for why
  encrypting the on-disk queue matters for a real deployment.
