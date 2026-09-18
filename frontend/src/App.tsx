import { useEffect, useState } from "react";
import "./App.css";
import { EDGE_API_URL, INGEST_API_URL, fetchEvents, fetchQueueStats } from "./api";
import type { FetchState, IngestedEvent, QueueStats } from "./types";

const EVENTS_POLL_MS = 4000;
const QUEUE_POLL_MS = 3000;

function formatTime(seconds: number | null): string {
  if (seconds === null) return "—";
  return new Date(seconds * 1000).toLocaleString();
}

function useEvents(): FetchState<IngestedEvent[]> {
  const [state, setState] = useState<FetchState<IngestedEvent[]>>({ status: "loading" });

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const events = await fetchEvents(50);
        if (!cancelled) setState({ status: "ok", data: events });
      } catch (err) {
        if (!cancelled) {
          setState({ status: "error", message: err instanceof Error ? err.message : String(err) });
        }
      }
    }

    load();
    const id = window.setInterval(load, EVENTS_POLL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, []);

  return state;
}

function useQueueStats(): FetchState<QueueStats> {
  const [state, setState] = useState<FetchState<QueueStats>>({ status: "loading" });

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const stats = await fetchQueueStats();
        if (!cancelled) setState({ status: "ok", data: stats });
      } catch (err) {
        if (!cancelled) {
          setState({ status: "error", message: err instanceof Error ? err.message : String(err) });
        }
      }
    }

    load();
    const id = window.setInterval(load, QUEUE_POLL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, []);

  return state;
}

function QueuePanel({ state }: { state: FetchState<QueueStats> }) {
  return (
    <section className="panel queue-panel" aria-label="Edge store-and-forward queue">
      <div className="panel-header">
        <h2>Edge queue (store-and-forward)</h2>
        <span className="panel-source">{EDGE_API_URL}/queue/stats</span>
      </div>
      {state.status === "loading" && <p className="muted">Loading queue stats…</p>}
      {state.status === "error" && (
        <div className="status-banner status-banner--warning">
          <strong>Edge site unreachable.</strong> This is expected during a
          simulated WAN outage — events keep queuing locally and will
          flush once the edge can reach the cloud again.
          <div className="status-banner-detail">{state.message}</div>
        </div>
      )}
      {state.status === "ok" && (
        <div className="stat-tiles">
          <div className="stat-tile stat-tile--warning">
            <span className="stat-tile-value">{state.data.pending}</span>
            <span className="stat-tile-label">Pending</span>
          </div>
          <div className="stat-tile stat-tile--good">
            <span className="stat-tile-value">{state.data.delivered}</span>
            <span className="stat-tile-label">Delivered</span>
          </div>
          <div className="stat-tile stat-tile--critical">
            <span className="stat-tile-value">{state.data.failed}</span>
            <span className="stat-tile-label">Failed</span>
          </div>
        </div>
      )}
    </section>
  );
}

function EventsTable({ state }: { state: FetchState<IngestedEvent[]> }) {
  return (
    <section className="panel events-panel" aria-label="Recently ingested events">
      <div className="panel-header">
        <h2>Recently ingested events</h2>
        <span className="panel-source">{INGEST_API_URL}/events</span>
      </div>
      {state.status === "loading" && <p className="muted">Loading events…</p>}
      {state.status === "error" && (
        <div className="status-banner status-banner--critical">
          <strong>Could not reach the cloud ingest API.</strong>
          <div className="status-banner-detail">{state.message}</div>
        </div>
      )}
      {state.status === "ok" && state.data.length === 0 && (
        <p className="muted">No events ingested yet.</p>
      )}
      {state.status === "ok" && state.data.length > 0 && (
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>ID</th>
                <th>Source</th>
                <th>Event type</th>
                <th>Data</th>
                <th>Event time</th>
                <th>Received</th>
              </tr>
            </thead>
            <tbody>
              {state.data.map((event) => (
                <tr key={event.id}>
                  <td className="mono">{event.id}</td>
                  <td>{event.source}</td>
                  <td>
                    <span className="event-type-badge">{event.event_type}</span>
                  </td>
                  <td className="mono data-cell">{JSON.stringify(event.data)}</td>
                  <td className="mono">{formatTime(event.event_timestamp)}</td>
                  <td className="mono">{formatTime(event.received_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

export default function App() {
  const eventsState = useEvents();
  const queueState = useQueueStats();

  return (
    <div className="app-shell">
      <header className="app-header">
        <h1>Hybrid Edge/Cloud Dashboard</h1>
        <p className="app-subtitle">
          Live view of the cloud ingest database and the edge site's
          store-and-forward queue — proof that events survive a WAN
          outage and flush once the link recovers.
        </p>
      </header>
      <main className="app-main">
        <QueuePanel state={queueState} />
        <EventsTable state={eventsState} />
      </main>
      <footer className="app-footer">
        <span>hybrid-edge-cloud-reference-architecture</span>
      </footer>
    </div>
  );
}
