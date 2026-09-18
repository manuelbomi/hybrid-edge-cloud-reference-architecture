"""
cloud/ingest_api.py

Minimal cloud-side ingestion endpoint.

Stands in for a managed ingestion service (an API gateway plus a
managed compute service behind a load balancer, in a real deployment).
It exposes ``POST /ingest``, which edge sites' ``Forwarder`` instances
call, and ``GET /events``, used by the demo dashboard and by tests.

Accepted events are written to SQLite, which here is a stand-in for a
managed database (e.g. RDS/Aurora/Cloud SQL). See ``infra/terraform/``
for an illustrative example of what that layer might look like in a
real cloud account.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel


class IngestEvent(BaseModel):
    """Shape of the event body edge Forwarders POST to /ingest.

    Mirrors ``edge.local_api.EventIn`` -- the edge queue stores the
    payload verbatim and forwards it unchanged, so the two schemas need
    to agree.
    """

    source: str
    event_type: str
    data: dict[str, Any] = {}
    timestamp: Optional[float] = None


def init_db(db_path: str) -> None:
    if db_path != ":memory:":
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ingested_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                event_type TEXT NOT NULL,
                data TEXT NOT NULL,
                event_timestamp REAL,
                received_at REAL NOT NULL
            )
            """
        )
        conn.commit()


@contextmanager
def _connect(db_path: str) -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def create_app(db_path: str) -> FastAPI:
    """Build the FastAPI app around a given SQLite database path.

    Taking the path as a parameter (rather than reading it from the
    environment at import time) makes this trivial to test: each test
    points at its own temp file, so tests never share state.
    """
    init_db(db_path)
    app = FastAPI(title="Cloud Ingest API")
    app.state.db_path = db_path

    # Permissive read-only CORS so a browser-based dashboard (frontend/,
    # served from its own origin/port) can poll GET /events. POST /ingest
    # is called server-to-server by edge Forwarders, not from a browser,
    # so it is intentionally left out of allow_methods -- this only adds
    # response headers for cross-origin GETs and does not change
    # ingestion behavior at all.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["GET"],
        allow_headers=["*"],
    )

    @app.post("/ingest", status_code=201)
    def ingest(event: IngestEvent) -> dict:
        now = time.time()
        with _connect(db_path) as conn:
            cur = conn.execute(
                """
                INSERT INTO ingested_events (source, event_type, data, event_timestamp, received_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (event.source, event.event_type, json.dumps(event.data), event.timestamp, now),
            )
            conn.commit()
            row_id = cur.lastrowid
        return {"stored": True, "id": row_id, "received_at": now}

    @app.get("/events")
    def list_events(limit: int = 50) -> list[dict]:
        with _connect(db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM ingested_events ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [
            {
                "id": r["id"],
                "source": r["source"],
                "event_type": r["event_type"],
                "data": json.loads(r["data"]),
                "event_timestamp": r["event_timestamp"],
                "received_at": r["received_at"],
            }
            for r in rows
        ]

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    return app


# Default app instance for `uvicorn cloud.ingest_api:app`.
app = create_app(os.environ.get("INGEST_DB_PATH", "./data/cloud_ingest.db"))
