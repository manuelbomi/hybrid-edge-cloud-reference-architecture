# Hybrid Edge/Cloud Dashboard (frontend)

A React + TypeScript dashboard for the
[hybrid-edge-cloud-reference-architecture](../README.md) repo. It replaces
the plain HTML page in `cloud/dashboard.py` as the human-facing view of the
system, without changing anything about how events are ingested or
store-and-forwarded.

It shows two things, side by side:

- **Recently ingested events** -- polls `GET /events` on `cloud/ingest_api.py`.
- **Edge queue (store-and-forward)** -- polls `GET /queue/stats` on
  `edge/local_api.py`, showing pending/delivered/failed counts from the
  edge site's local SQLite queue (`edge/forwarder.py`).

Both panels poll independently and fail independently -- the edge panel
going into an "unreachable" state while the cloud panel keeps showing data
is expected and is literally the scenario this repo is about (a WAN outage
at the edge site).

See the root [README.md's "Dashboard" section](../README.md#dashboard) for
how to run this against the rest of the stack.

## Local development

```bash
npm install
cp .env.example .env   # adjust VITE_INGEST_API_URL / VITE_EDGE_API_URL if needed
npm run dev
```

## Type-check & build

```bash
npx tsc --noEmit
npm run build   # tsc -b && vite build -> dist/
```

## Project layout

- `src/types.ts` -- TypeScript interfaces mirroring the real API response
  shapes (`IngestedEvent`, `QueueStats`) -- kept in lockstep with
  `cloud/ingest_api.py` and `edge/local_api.py`.
- `src/api.ts` -- small `fetch` wrappers for the two endpoints above.
- `src/App.tsx` -- the dashboard itself: an events table and a queue-stats
  panel with polling and per-panel error states.
- `Dockerfile` -- multi-stage build (Node build -> nginx serve), used by the
  `dashboard-ui` service in `../docker-compose.cloud.yml`.
