"""
Tests for edge/forwarder.py -- the store-and-forward centerpiece of this repo.

These tests exercise the real `Forwarder` class against a real (temp file)
SQLite database, but replace the network call with an `httpx.MockTransport`
so the "cloud endpoint" can be toggled up/down deterministically, and inject
a fake clock so backoff/TTL behavior can be tested without real sleeping.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from edge.forwarder import STATUS_DELIVERED, STATUS_PENDING, Forwarder
from tests.conftest import FakeClock, RecordingEndpoint, make_mock_client


def make_forwarder(
    tmp_path: Path,
    endpoint: RecordingEndpoint,
    clock: FakeClock,
    **overrides,
) -> Forwarder:
    db_path = str(tmp_path / "edge_queue.db")
    client = make_mock_client(endpoint.handler)
    kwargs = dict(
        db_path=db_path,
        cloud_endpoint="/ingest",
        http_client=client,
        base_backoff_seconds=1.0,
        max_backoff_seconds=100.0,
        ttl_seconds=3600.0,
        poll_interval_seconds=0.01,
        clock=clock,
    )
    kwargs.update(overrides)
    return Forwarder(**kwargs)


@pytest.mark.asyncio
async def test_endpoint_down_events_stay_pending_with_growing_backoff(tmp_path, recording_endpoint, fake_clock):
    """When the cloud is unreachable, events queue up as pending and
    attempt_count increments with exponential backoff between retries."""
    recording_endpoint.up = False
    forwarder = make_forwarder(tmp_path, recording_endpoint, fake_clock)

    event_id = forwarder.enqueue({"source": "camera-01", "event_type": "motion_detected"})

    # First attempt: fails, attempt_count becomes 1, backoff = 1 * 2**1 = 2s.
    summary = await forwarder.deliver_pending()
    assert summary == {"attempted": 1, "delivered": 0, "failed": 1}

    ev = forwarder.get_event(event_id)
    assert ev.status == STATUS_PENDING
    assert ev.attempt_count == 1
    assert ev.next_attempt_at == pytest.approx(fake_clock() + 2.0)

    # Retrying immediately (before the backoff window elapses) should be a
    # no-op: the event isn't due for another attempt yet.
    summary = await forwarder.deliver_pending()
    assert summary == {"attempted": 0, "delivered": 0, "failed": 0}
    assert forwarder.get_event(event_id).attempt_count == 1

    # Advance the clock past the backoff window: second attempt fails too,
    # attempt_count becomes 2, backoff = 1 * 2**2 = 4s (growing).
    fake_clock.advance(2.5)
    summary = await forwarder.deliver_pending()
    assert summary == {"attempted": 1, "delivered": 0, "failed": 1}

    ev = forwarder.get_event(event_id)
    assert ev.status == STATUS_PENDING
    assert ev.attempt_count == 2
    assert ev.next_attempt_at == pytest.approx(fake_clock() + 4.0)

    # Third failure: attempt_count becomes 3, backoff = 1 * 2**3 = 8s.
    fake_clock.advance(4.5)
    await forwarder.deliver_pending()
    ev = forwarder.get_event(event_id)
    assert ev.attempt_count == 3
    assert ev.next_attempt_at == pytest.approx(fake_clock() + 8.0)

    assert recording_endpoint.request_count == 3


@pytest.mark.asyncio
async def test_endpoint_recovering_flushes_queue_in_order(tmp_path, recording_endpoint, fake_clock):
    """Events queued while the cloud is down should all flush, in the order
    they were created, once the cloud comes back up -- and get marked
    delivered."""
    recording_endpoint.up = False
    forwarder = make_forwarder(tmp_path, recording_endpoint, fake_clock)

    ids = []
    for i in range(3):
        event_id = forwarder.enqueue({"id": i, "source": f"camera-{i:02d}", "event_type": "motion_detected"})
        ids.append(event_id)

    # All three fail while the cloud is down.
    summary = await forwarder.deliver_pending()
    assert summary == {"attempted": 3, "delivered": 0, "failed": 3}
    for event_id in ids:
        ev = forwarder.get_event(event_id)
        assert ev.status == STATUS_PENDING
        assert ev.attempt_count == 1

    # Advance past the backoff window and bring the cloud back up.
    fake_clock.advance(5.0)
    recording_endpoint.up = True

    summary = await forwarder.deliver_pending()
    assert summary == {"attempted": 3, "delivered": 3, "failed": 0}

    for event_id in ids:
        ev = forwarder.get_event(event_id)
        assert ev.status == STATUS_DELIVERED
        assert ev.delivered_at is not None

    # Delivered in creation order (0, 1, 2), matching how they were enqueued.
    assert recording_endpoint.received_ids == [0, 1, 2]


@pytest.mark.asyncio
async def test_purge_delivered_removes_delivered_events(tmp_path, recording_endpoint, fake_clock):
    """Once an event is delivered, purge_delivered() should remove it from
    the local queue -- the cloud is now the system of record for it."""
    forwarder = make_forwarder(tmp_path, recording_endpoint, fake_clock)

    event_id = forwarder.enqueue({"source": "camera-01", "event_type": "motion_detected"})
    await forwarder.deliver_pending()
    assert forwarder.get_event(event_id).status == STATUS_DELIVERED

    removed = forwarder.purge_delivered()
    assert removed == 1
    assert forwarder.get_event(event_id) is None


@pytest.mark.asyncio
async def test_ttl_purge_removes_only_expired_undelivered_events(tmp_path, recording_endpoint, fake_clock):
    """Undelivered events older than the configured TTL get purged (the
    data retention policy); events still within the TTL window are kept."""
    recording_endpoint.up = False
    forwarder = make_forwarder(tmp_path, recording_endpoint, fake_clock, ttl_seconds=100.0)

    old_event_id = forwarder.enqueue({"source": "camera-old", "event_type": "motion_detected"})

    # Move the clock forward most of the way, enqueue a second, newer event.
    fake_clock.advance(80.0)
    new_event_id = forwarder.enqueue({"source": "camera-new", "event_type": "motion_detected"})

    # Both still fail to deliver (cloud down) but that's independent of TTL.
    await forwarder.deliver_pending()

    # Advance past the TTL window for the *old* event only (100s from when
    # it was created), but not for the new one (created 80s later).
    fake_clock.advance(25.0)  # old event is now 105s old; new event is 25s old

    removed = forwarder.purge_expired()
    assert removed == 1
    assert forwarder.get_event(old_event_id) is None
    assert forwarder.get_event(new_event_id) is not None


@pytest.mark.asyncio
async def test_ttl_purge_does_not_remove_delivered_events(tmp_path, recording_endpoint, fake_clock):
    """purge_expired() enforces retention for *undelivered* events only;
    delivered events are handled by purge_delivered() instead, regardless of
    age."""
    forwarder = make_forwarder(tmp_path, recording_endpoint, fake_clock, ttl_seconds=10.0)

    event_id = forwarder.enqueue({"source": "camera-01", "event_type": "motion_detected"})
    await forwarder.deliver_pending()
    assert forwarder.get_event(event_id).status == STATUS_DELIVERED

    fake_clock.advance(100.0)  # well past the TTL
    removed = forwarder.purge_expired()

    assert removed == 0
    assert forwarder.get_event(event_id) is not None


@pytest.mark.asyncio
async def test_run_forever_delivers_and_can_be_stopped(tmp_path, recording_endpoint, fake_clock):
    """The background loop should pick up a queued event, deliver it, and
    (per each loop iteration also calling purge_delivered()) clear it from
    the local queue -- then stop cleanly when asked to."""
    forwarder = make_forwarder(tmp_path, recording_endpoint, fake_clock, poll_interval_seconds=0.01)
    event_id = forwarder.enqueue({"source": "camera-01", "event_type": "motion_detected"})

    forwarder.start()

    import asyncio

    for _ in range(50):
        await asyncio.sleep(0.01)
        if recording_endpoint.request_count >= 1:
            break

    await forwarder.stop()

    # The event was delivered (the mock cloud endpoint received it) and the
    # same loop iteration's purge_delivered() call then removed it from the
    # local queue -- so by the time we check, it's gone.
    assert recording_endpoint.request_count == 1
    assert recording_endpoint.received_ids == ["camera-01"]
    assert forwarder.get_event(event_id) is None
