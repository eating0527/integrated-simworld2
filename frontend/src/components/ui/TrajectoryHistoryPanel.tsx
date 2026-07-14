import { useCallback, useEffect, useState } from 'react';
import { MinPanel } from './MinPanel';
import { PanelEmpty, PanelField, PanelFooter, PanelGrid, PanelStatus } from './PanelUi';

const API = import.meta.env.VITE_API_URL || '';

export interface TrajectoryPoint {
  lat: number;
  lon: number;
  alt?: number;
  accuracy?: number;
  timestamp?: number | string;
  deviceId?: string;
  deviceName?: string;
  deviceType?: string;
}

export interface TrajectoryDevice {
  deviceId: string;
  deviceName?: string;
  deviceType?: string;
  pointCount: number;
  startTimestamp?: number | string;
  endTimestamp?: number | string;
  points: TrajectoryPoint[];
}

export interface TrajectoryEventSummary {
  id: string;
  missionId?: string | null;
  createdAt?: string;
  startedAt?: string;
  endedAt?: string;
  deviceCount: number;
  pointCount: number;
  filename?: string;
  url?: string;
}

export interface TrajectoryEvent extends TrajectoryEventSummary {
  devices: TrajectoryDevice[];
}

interface TrajectoryHistoryPanelProps {
  selectedEventId: string | null;
  onSelectEvent: (event: TrajectoryEvent | null) => void;
}

function formatDate(value?: string | number | null): string {
  if (!value) return '-';
  const date = typeof value === 'number' ? new Date(value * 1000) : new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleString();
}

async function fetchEvents(): Promise<TrajectoryEventSummary[]> {
  const res = await fetch(`${API}/api/trajectory-events`);
  if (!res.ok) throw new Error(`Failed to load trajectory events: ${res.status}`);
  const payload = await res.json();
  return Array.isArray(payload?.events) ? payload.events as TrajectoryEventSummary[] : [];
}

async function fetchEvent(id: string): Promise<TrajectoryEvent> {
  const res = await fetch(`${API}/api/trajectory-events/${encodeURIComponent(id)}`);
  if (!res.ok) throw new Error(`Failed to load trajectory event: ${res.status}`);
  const payload = await res.json();
  return payload.event as TrajectoryEvent;
}

export function TrajectoryHistoryPanel({ selectedEventId, onSelectEvent }: TrajectoryHistoryPanelProps) {
  const [events, setEvents] = useState<TrajectoryEventSummary[]>([]);
  const [status, setStatus] = useState<'idle' | 'loading' | 'error'>('idle');
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setStatus('loading');
    setError(null);
    try {
      setEvents(await fetchEvents());
      setStatus('idle');
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setStatus('error');
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const selectEvent = useCallback(async (id: string) => {
    setStatus('loading');
    setError(null);
    try {
      const event = await fetchEvent(id);
      onSelectEvent(event);
      setStatus('idle');
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setStatus('error');
    }
  }, [onSelectEvent]);

  const selected = events.find(event => event.id === selectedEventId) ?? null;

  return (
    <MinPanel
      title="歷史軌跡"
      className="panel-ui trajectory-history-panel"
      defaultMinimized
      actions={
        <button type="button" className="trajectory-history-panel__icon-btn" onClick={() => void refresh()}>
          Refresh
        </button>
      }
    >
      <PanelGrid>
        <PanelField label="Events" value={events.length} />
        <PanelField label="Selected" value={selected ? selected.pointCount : '-'} />
      </PanelGrid>

      {status === 'error' && <PanelEmpty>{error}</PanelEmpty>}
      {events.length === 0 && status !== 'loading' && <PanelEmpty>No trajectory events saved yet.</PanelEmpty>}
      {status === 'loading' && <PanelStatus label="Loading" tone="waiting" />}

      <div className="trajectory-history-panel__list">
        {events.map(event => {
          const active = event.id === selectedEventId;
          return (
            <button
              key={event.id}
              type="button"
              className={`trajectory-history-panel__item${active ? ' is-active' : ''}`}
              onClick={() => void selectEvent(event.id)}
            >
              <span className="trajectory-history-panel__item-title">
                {event.missionId || event.id}
              </span>
              <span className="trajectory-history-panel__item-meta">
                {event.pointCount} pts · {event.deviceCount} device
              </span>
              <span className="trajectory-history-panel__item-meta">
                {formatDate(event.createdAt)}
              </span>
            </button>
          );
        })}
      </div>

      <PanelFooter>
        <button type="button" className="trajectory-history-panel__link-btn" onClick={() => onSelectEvent(null)}>
          Clear overlay
        </button>
        <span>{selected ? formatDate(selected.createdAt) : 'No overlay'}</span>
      </PanelFooter>
    </MinPanel>
  );
}
