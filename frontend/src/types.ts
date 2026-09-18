/**
 * Shared types for the hybrid edge/cloud dashboard.
 *
 * These interfaces are intentionally kept in lockstep with the real
 * response shapes returned by the Python services in this repo:
 *
 * - `IngestedEvent` mirrors the rows returned by
 *   `GET /events` in `cloud/ingest_api.py` (see `list_events`).
 * - `QueueStats` mirrors the response of `GET /queue/stats` in
 *   `edge/local_api.py`, which summarizes the store-and-forward queue
 *   (`edge/forwarder.py`'s `Forwarder.counts()`) by status.
 *
 * If either Python response shape changes, update these interfaces to
 * match -- they are not meant to diverge from the real API.
 */

/** One event as stored by the cloud ingest API (`ingested_events` table). */
export interface IngestedEvent {
  /** Auto-increment primary key assigned by the cloud database. */
  id: number;
  /** Where the event originated, e.g. a camera id like "camera-01". */
  source: string;
  /** e.g. "motion_detected", "person_detected", "vehicle_detected", "no_event". */
  event_type: string;
  /** Free-form event payload (e.g. `{ confidence, zone }` for camera events). */
  data: Record<string, unknown>;
  /** Unix seconds when the event actually happened, set at the edge. May be absent. */
  event_timestamp: number | null;
  /** Unix seconds when the cloud ingest API received/stored the event. */
  received_at: number;
}

/**
 * Status breakdown of the edge site's local store-and-forward queue, as
 * returned by `GET /queue/stats` on `edge/local_api.py`. Counts reflect
 * `edge/forwarder.py`'s queue table statuses at the moment of the request.
 */
export interface QueueStats {
  /** Queued locally, not yet acknowledged by the cloud ingest API. */
  pending: number;
  /** Acknowledged by the cloud (2xx); awaiting the forwarder's next purge sweep. */
  delivered: number;
  /** Exceeded `max_attempts` (if configured) and stopped retrying. */
  failed: number;
}

/** Discriminated fetch state used for both the events list and queue stats panels. */
export type FetchState<T> =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ok"; data: T };
