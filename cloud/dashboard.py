"""
cloud/dashboard.py

A deliberately tiny "dashboard" for the cloud side of the demo: it
polls the ingest API's ``GET /events`` endpoint and renders the most
recent events as a plain HTML table.

In a production system this would be a real BI tool or a proper
frontend. Here it is just enough to prove, end to end, that an event
generated at an edge site made it through the local queue, survived
being written to store-and-forward SQLite, crossed the WAN, and landed
in the cloud ingestion API where a human (or another system) can see it.
"""

from __future__ import annotations

import html
import os
from typing import Optional

import httpx
from fastapi import FastAPI
from fastapi.responses import HTMLResponse

INGEST_API_URL = os.environ.get("INGEST_API_URL", "http://localhost:8080")


def _render_table(events: Optional[list[dict]]) -> str:
    if not events:
        return "<tr><td colspan='5'>no events yet</td></tr>"
    rows = []
    for e in events:
        rows.append(
            "<tr>"
            f"<td>{html.escape(str(e.get('id')))}</td>"
            f"<td>{html.escape(str(e.get('source')))}</td>"
            f"<td>{html.escape(str(e.get('event_type')))}</td>"
            f"<td>{html.escape(str(e.get('event_timestamp')))}</td>"
            f"<td>{html.escape(str(e.get('received_at')))}</td>"
            "</tr>"
        )
    return "".join(rows)


def create_app(ingest_api_url: str) -> FastAPI:
    app = FastAPI(title="Cloud Dashboard")
    app.state.ingest_api_url = ingest_api_url

    @app.get("/", response_class=HTMLResponse)
    async def index() -> str:
        events: Optional[list[dict]] = None
        error: Optional[str] = None
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{ingest_api_url}/events", params={"limit": 50})
                resp.raise_for_status()
                events = resp.json()
        except httpx.HTTPError as exc:
            error = str(exc)

        body_rows = _render_table(events)
        error_banner = (
            f"<p style='color:#b00'>could not reach ingest API: {html.escape(error)}</p>" if error else ""
        )

        return f"""
        <html>
          <head><title>Cloud Ingest Dashboard</title></head>
          <body style="font-family: sans-serif; margin: 2rem;">
            <h1>Recently ingested events</h1>
            {error_banner}
            <table border="1" cellpadding="6" cellspacing="0">
              <thead>
                <tr>
                  <th>id</th><th>source</th><th>event_type</th>
                  <th>event_timestamp</th><th>received_at</th>
                </tr>
              </thead>
              <tbody>{body_rows}</tbody>
            </table>
          </body>
        </html>
        """

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    return app


# Default app instance for `uvicorn cloud.dashboard:app`.
app = create_app(INGEST_API_URL)
