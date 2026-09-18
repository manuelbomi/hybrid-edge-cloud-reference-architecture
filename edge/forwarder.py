"""
edge/forwarder.py

Store-and-forward service for edge sites with unreliable WAN links.

Problem this solves
--------------------
Edge sites (retail stores, warehouses, factory floors, remote clinics,
etc.) generate events locally -- camera detections, sensor readings, and
so on -- that need to end up in a central cloud system for storage,
analytics, and reporting. The WAN link between an edge site and the
cloud is not always up, and it is not always fast. If the edge software
requires a synchronous, successful HTTP call to the cloud before it
considers an event "done," any WAN blip causes either lost events or a
backed-up local system.

This module implements the classic "store-and-forward" pattern:

1. Every event accepted locally is written to a durable, local SQLite
   queue *before* any attempt is made to deliver it to the cloud.
2. A background loop repeatedly tries to deliver whatever is pending,
   using exponential backoff between retries for events that keep
   failing.
3. Events are removed from the queue once the cloud has acknowledged
   them (HTTP 2xx), or once they have been sitting in the queue longer
   than a configured retention window (TTL) with no successful
   delivery.

This gives "at least once" delivery to the cloud without ever blocking
whatever is producing events, and without silently dropping data during
a network outage of a normal, bounded duration.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

import httpx

logger = logging.getLogger("edge.forwarder")

STATUS_PENDING = "pending"
STATUS_DELIVERED = "delivered"
STATUS_FAILED = "failed"


@dataclass
class QueuedEvent:
    """In-memory view of one row of the local queue table."""

    id: int
    payload: dict[str, Any]
    status: str
    attempt_count: int
    created_at: float
    last_attempt_at: Optional[float]
    next_attempt_at: float
    delivered_at: Optional[float]


class Forwarder:
    """Durable local queue plus a delivery loop for a single cloud endpoint.

    Instances of this class are used two ways in this repo:

    * Embedded directly in a test (or in ``edge/local_api.py``) to call
      ``enqueue()`` / ``deliver_pending()`` / ``purge_*()`` directly.
    * Run standalone via ``python -m edge.forwarder`` as its own process
      (see ``docker-compose.edge.yml``), continuously delivering
      whatever ``edge/local_api.py`` (or an MQTT bridge) has queued.
    """

    def __init__(
        self,
        db_path: str,
        cloud_endpoint: str,
        *,
        http_client: Optional[httpx.AsyncClient] = None,
        base_backoff_seconds: float = 1.0,
        max_backoff_seconds: float = 300.0,
        max_attempts: Optional[int] = None,
        ttl_seconds: float = 24 * 60 * 60,
        poll_interval_seconds: float = 1.0,
        request_timeout_seconds: float = 5.0,
        clock: Callable[[], float] = time.time,
    ) -> None:
        """
        Args:
            db_path: path to the SQLite file backing the local queue.
            cloud_endpoint: full URL of the cloud ingestion endpoint
                (e.g. ``https://ingest.example.com/ingest``).
            http_client: an ``httpx.AsyncClient`` to use for delivery.
                If omitted, one is created lazily. Tests inject a client
                built with ``httpx.MockTransport`` to simulate the cloud
                endpoint being up or down without any real network call.
            base_backoff_seconds: the first retry waits roughly this long.
            max_backoff_seconds: retries never wait longer than this.
            max_attempts: if set, an event is marked ``failed`` (a
                terminal state) after this many failed attempts instead
                of retrying forever. If ``None`` (the default), events
                keep retrying until they are delivered or purged by TTL.
            ttl_seconds: data retention window. An undelivered event
                older than this is purged by ``purge_expired()``.
            poll_interval_seconds: how often the background loop wakes
                up to check for work.
            request_timeout_seconds: per-request HTTP timeout.
            clock: injectable time source (seconds since epoch). Tests
                use a fake clock so backoff/TTL behavior can be tested
                without real sleeping.
        """
        self.db_path = db_path
        self.cloud_endpoint = cloud_endpoint
        self._client = http_client
        self._owns_client = http_client is None
        self.base_backoff_seconds = base_backoff_seconds
        self.max_backoff_seconds = max_backoff_seconds
        self.max_attempts = max_attempts
        self.ttl_seconds = ttl_seconds
        self.poll_interval_seconds = poll_interval_seconds
        self.request_timeout_seconds = request_timeout_seconds
        self._clock = clock
        self._task: Optional[asyncio.Task] = None
        self._stop_event: Optional[asyncio.Event] = None

        if self.db_path != ":memory:":
            parent = Path(self.db_path).parent
            if str(parent) not in ("", "."):
                parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    # ------------------------------------------------------------------
    # DB setup / connection helpers
    # ------------------------------------------------------------------
    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    payload TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    created_at REAL NOT NULL,
                    last_attempt_at REAL,
                    next_attempt_at REAL NOT NULL,
                    delivered_at REAL
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_events_status ON events(status)")
            conn.commit()

    # ------------------------------------------------------------------
    # Public queue API
    # ------------------------------------------------------------------
    def enqueue(self, event: dict[str, Any]) -> int:
        """Persist an event to the local queue. Returns the new row id.

        This is the "store" half of store-and-forward: the caller gets
        an id back as soon as the event is durably on disk, regardless
        of whether the cloud is currently reachable.
        """
        now = self._clock()
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO events (payload, status, attempt_count, created_at, next_attempt_at)
                VALUES (?, ?, 0, ?, ?)
                """,
                (json.dumps(event), STATUS_PENDING, now, now),
            )
            conn.commit()
            return int(cur.lastrowid)

    def get_event(self, event_id: int) -> Optional[QueuedEvent]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
            return self._row_to_event(row) if row else None

    def list_events(self, status: Optional[str] = None) -> list[QueuedEvent]:
        with self._connect() as conn:
            if status:
                rows = conn.execute(
                    "SELECT * FROM events WHERE status = ? ORDER BY id ASC", (status,)
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM events ORDER BY id ASC").fetchall()
            return [self._row_to_event(r) for r in rows]

    def counts(self) -> dict[str, int]:
        """Small summary used by the health endpoint / demo dashboard."""
        with self._connect() as conn:
            rows = conn.execute("SELECT status, COUNT(*) as n FROM events GROUP BY status").fetchall()
            return {r["status"]: r["n"] for r in rows}

    @staticmethod
    def _row_to_event(row: sqlite3.Row) -> QueuedEvent:
        return QueuedEvent(
            id=row["id"],
            payload=json.loads(row["payload"]),
            status=row["status"],
            attempt_count=row["attempt_count"],
            created_at=row["created_at"],
            last_attempt_at=row["last_attempt_at"],
            next_attempt_at=row["next_attempt_at"],
            delivered_at=row["delivered_at"],
        )

    # ------------------------------------------------------------------
    # Delivery
    # ------------------------------------------------------------------
    def _compute_backoff(self, attempt_count: int) -> float:
        delay = self.base_backoff_seconds * (2 ** attempt_count)
        return min(delay, self.max_backoff_seconds)

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.request_timeout_seconds)
        return self._client

    async def deliver_pending(self) -> dict[str, int]:
        """Attempt delivery of every pending event whose retry time has arrived.

        Events are delivered in the order they were created (oldest
        first), so a burst of events queued during an outage is flushed
        to the cloud in the same order it happened, once the link comes
        back.

        Returns a small summary dict, useful for logging/observability.
        """
        now = self._clock()
        summary = {"attempted": 0, "delivered": 0, "failed": 0}

        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM events
                WHERE status = ? AND next_attempt_at <= ?
                ORDER BY id ASC
                """,
                (STATUS_PENDING, now),
            ).fetchall()

        events = [self._row_to_event(r) for r in rows]
        client = await self._get_client()

        for ev in events:
            summary["attempted"] += 1
            delivered = await self._attempt_delivery(client, ev)
            if delivered:
                summary["delivered"] += 1
            else:
                summary["failed"] += 1

        return summary

    async def _attempt_delivery(self, client: httpx.AsyncClient, ev: QueuedEvent) -> bool:
        now = self._clock()
        try:
            response = await client.post(self.cloud_endpoint, json=ev.payload)
            success = 200 <= response.status_code < 300
        except httpx.HTTPError as exc:
            logger.warning("delivery attempt failed for event %s: %s", ev.id, exc)
            success = False

        attempt_count = ev.attempt_count + 1

        with self._connect() as conn:
            if success:
                conn.execute(
                    """
                    UPDATE events
                    SET status = ?, attempt_count = ?, last_attempt_at = ?, delivered_at = ?
                    WHERE id = ?
                    """,
                    (STATUS_DELIVERED, attempt_count, now, now, ev.id),
                )
            else:
                next_status = STATUS_PENDING
                if self.max_attempts is not None and attempt_count >= self.max_attempts:
                    next_status = STATUS_FAILED
                backoff = self._compute_backoff(attempt_count)
                conn.execute(
                    """
                    UPDATE events
                    SET status = ?, attempt_count = ?, last_attempt_at = ?, next_attempt_at = ?
                    WHERE id = ?
                    """,
                    (next_status, attempt_count, now, now + backoff, ev.id),
                )
            conn.commit()

        return success

    # ------------------------------------------------------------------
    # Retention / purge
    # ------------------------------------------------------------------
    def purge_delivered(self) -> int:
        """Remove events that were already delivered to the cloud.

        Once the cloud has acknowledged an event there is no reason to
        keep a copy at the edge; the cloud's database is now the system
        of record for it.
        """
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM events WHERE status = ?", (STATUS_DELIVERED,))
            conn.commit()
            return cur.rowcount

    def purge_expired(self) -> int:
        """Enforce the data retention policy for undelivered events.

        Any event that has not been delivered within ``ttl_seconds`` of
        being created is dropped, whether it is still ``pending`` or has
        already been marked ``failed``. This bounds how much undelivered
        data can pile up locally during a long outage, and how long
        stale, likely-irrelevant events (e.g. a camera detection from
        three days ago) linger on edge hardware with limited storage.
        """
        cutoff = self._clock() - self.ttl_seconds
        with self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM events WHERE status != ? AND created_at < ?",
                (STATUS_DELIVERED, cutoff),
            )
            conn.commit()
            return cur.rowcount

    # ------------------------------------------------------------------
    # Background loop
    # ------------------------------------------------------------------
    async def run_forever(self) -> None:
        """Continuously deliver pending events and enforce retention.

        Runs until ``stop()`` is called. Any unexpected error in a
        single iteration is logged and swallowed so a transient bug (or
        a flaky mock in a test) cannot permanently kill the loop.
        """
        self._stop_event = asyncio.Event()
        while not self._stop_event.is_set():
            try:
                await self.deliver_pending()
                self.purge_delivered()
                self.purge_expired()
            except Exception:  # noqa: BLE001 - keep the loop alive
                logger.exception("forwarder loop iteration failed")
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=self.poll_interval_seconds)
            except asyncio.TimeoutError:
                pass

    def start(self) -> None:
        """Start the background loop as an asyncio task (idempotent)."""
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self.run_forever())

    async def stop(self) -> None:
        """Stop the background loop and close any owned HTTP client."""
        if self._stop_event is not None:
            self._stop_event.set()
        if self._task is not None:
            await self._task
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None


async def _main() -> None:
    """Entry point for running the forwarder as its own process/container."""
    import os

    logging.basicConfig(level=logging.INFO)

    db_path = os.environ.get("FORWARDER_DB_PATH", "./data/edge_queue.db")
    cloud_endpoint = os.environ.get("CLOUD_INGEST_URL", "http://localhost:8080/ingest")

    forwarder = Forwarder(
        db_path=db_path,
        cloud_endpoint=cloud_endpoint,
        base_backoff_seconds=float(os.environ.get("BASE_BACKOFF_SECONDS", "1.0")),
        max_backoff_seconds=float(os.environ.get("MAX_BACKOFF_SECONDS", "300.0")),
        ttl_seconds=float(os.environ.get("TTL_SECONDS", str(24 * 60 * 60))),
        poll_interval_seconds=float(os.environ.get("POLL_INTERVAL_SECONDS", "2.0")),
    )

    logger.info("forwarder starting, delivering to %s", cloud_endpoint)
    await forwarder.run_forever()


if __name__ == "__main__":
    asyncio.run(_main())
