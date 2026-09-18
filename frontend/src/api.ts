import type { IngestedEvent, QueueStats } from "./types";

/**
 * Base URL of `cloud/ingest_api.py`. Configurable at build time via
 * `VITE_INGEST_API_URL` (see `frontend/.env.example` and the
 * `dashboard-ui` service in `docker-compose.cloud.yml`); defaults to the
 * same host/port the README's manual setup instructions use.
 */
export const INGEST_API_URL: string =
  import.meta.env.VITE_INGEST_API_URL ?? "http://localhost:8080";

/**
 * Base URL of `edge/local_api.py`, whose `/queue/stats` endpoint powers
 * the store-and-forward queue panel. It is entirely normal for this to
 * be unreachable -- that's the whole point of store-and-forward -- so
 * callers must handle a failed fetch gracefully rather than treating it
 * as fatal.
 */
export const EDGE_API_URL: string =
  import.meta.env.VITE_EDGE_API_URL ?? "http://localhost:8000";

async function fetchJson<T>(url: string): Promise<T> {
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`${url} responded ${response.status}`);
  }
  return (await response.json()) as T;
}

/** Fetch the most recently ingested events from the cloud ingest API. */
export function fetchEvents(limit = 50): Promise<IngestedEvent[]> {
  return fetchJson<IngestedEvent[]>(`${INGEST_API_URL}/events?limit=${limit}`);
}

/** Fetch pending/delivered/failed counts for the edge store-and-forward queue. */
export function fetchQueueStats(): Promise<QueueStats> {
  return fetchJson<QueueStats>(`${EDGE_API_URL}/queue/stats`);
}
