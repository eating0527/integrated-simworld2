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

export interface MissionBundleArtifact {
  kind: 'gps' | 'noise';
  filename: string;
  url?: string | null;
  exists: boolean;
  healthy: boolean;
  status: string;
  header?: string[] | null;
  size: number;
  sha256?: string | null;
  changed?: boolean;
}

export interface MissionBundle {
  mission_id: string;
  missionId?: string;
  updated_at?: string | null;
  metadata?: Record<string, unknown>;
  metadata_only?: boolean;
  labels: string[];
  badges?: string[];
  gps: MissionBundleArtifact;
  noise: MissionBundleArtifact;
  artifacts?: { gps: MissionBundleArtifact; noise: MissionBundleArtifact };
  trajectory?: TrajectoryEvent | null;
}

interface TrajectoryHistoryPanelProps {
  selectedEventId: string | null;
  onSelectEvent: (event: TrajectoryEvent | null) => void;
  selectedBundleId?: string | null;
  onApplyToSimulation?: (files: { missionId: string; gpsFile?: File; noiseFile?: File }) => void;
}

function formatDate(value?: string | number | null): string {
  if (!value) return '-';
  const date = typeof value === 'number' ? new Date(value * 1000) : new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleString();
}

function labelsFor(bundle: MissionBundle): string[] {
  if (Array.isArray(bundle.labels) && bundle.labels.length > 0) return bundle.labels;
  const labels = [
    bundle.gps?.healthy ? '[GPS]' : '',
    bundle.noise?.healthy ? '[NOISE]' : '',
  ].filter(Boolean);
  return labels.length > 0 ? labels : ['[N/A]'];
}

async function fetchBundles(): Promise<MissionBundle[]> {
  const res = await fetch(`${API}/api/mission-bundles`);
  if (!res.ok) throw new Error(`Failed to load mission bundles: ${res.status}`);
  const payload = await res.json();
  return Array.isArray(payload?.bundles)
    ? payload.bundles as MissionBundle[]
    : Array.isArray(payload?.missions) ? payload.missions as MissionBundle[] : [];
}

async function fetchBundle(id: string): Promise<MissionBundle> {
  const res = await fetch(`${API}/api/mission-bundles/${encodeURIComponent(id)}`);
  if (!res.ok) throw new Error(`Failed to load mission bundle: ${res.status}`);
  const payload = await res.json();
  return (payload?.bundle ?? payload) as MissionBundle;
}

async function importBundles(): Promise<void> {
  const res = await fetch(`${API}/api/mission-bundles/import`, { method: 'POST' });
  if (!res.ok) throw new Error(`Failed to import mission bundles: ${res.status}`);
}

function artifactFetchUrl(url: string): string {
  // The URL is supplied by the backend.  Restrict it to the CSV artifact API
  // before concatenating VITE_API_URL so an imported metadata value cannot turn
  // the Apply action into an arbitrary browser fetch.
  if (!url.startsWith('/api/mission-bundles/')) throw new Error('Invalid mission artifact URL');
  return `${API}${url}`;
}

async function fetchArtifactFile(artifact: MissionBundleArtifact): Promise<File> {
  if (!artifact.url || !artifact.healthy) throw new Error(`${artifact.kind} artifact is not healthy`);
  const res = await fetch(artifactFetchUrl(artifact.url));
  if (!res.ok) throw new Error(`Failed to download ${artifact.filename}: ${res.status}`);
  const blob = await res.blob();
  return new File([blob], artifact.filename, { type: blob.type || 'text/csv' });
}

export function TrajectoryHistoryPanel({
  selectedEventId,
  onSelectEvent,
  selectedBundleId,
  onApplyToSimulation,
}: TrajectoryHistoryPanelProps) {
  const [bundles, setBundles] = useState<MissionBundle[]>([]);
  const [selectedBundle, setSelectedBundle] = useState<MissionBundle | null>(null);
  const [status, setStatus] = useState<'idle' | 'loading' | 'error'>('idle');
  const [error, setError] = useState<string | null>(null);
  const [applying, setApplying] = useState(false);
  const [applyMessage, setApplyMessage] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setStatus('loading');
    setError(null);
    try {
      setBundles(await fetchBundles());
      setStatus('idle');
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setStatus('error');
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const selectBundle = useCallback(async (id: string) => {
    setStatus('loading');
    setError(null);
    setApplyMessage(null);
    try {
      const bundle = await fetchBundle(id);
      setSelectedBundle(bundle);
      // A bundle click is intentionally a GPS-only overlay operation. Noise is
      // available for the explicit Apply action below and never becomes a path.
      onSelectEvent(bundle.trajectory ?? null);
      setStatus('idle');
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setStatus('error');
    }
  }, [onSelectEvent]);

  const importIncoming = useCallback(async () => {
    setStatus('loading');
    setError(null);
    try {
      await importBundles();
      setBundles(await fetchBundles());
      setStatus('idle');
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setStatus('error');
    }
  }, []);

  const applyToSimulation = useCallback(async () => {
    if (!selectedBundle || !onApplyToSimulation) return;
    setApplying(true);
    setApplyMessage(null);
    const files: { missionId: string; gpsFile?: File; noiseFile?: File } = {
      missionId: selectedBundle.mission_id,
    };
    const failures: string[] = [];
    try {
      const downloads: Array<Promise<void>> = [];
      if (selectedBundle.gps?.healthy) {
        downloads.push(fetchArtifactFile(selectedBundle.gps).then(file => { files.gpsFile = file; }).catch(err => {
          failures.push(err instanceof Error ? err.message : String(err));
        }));
      }
      if (selectedBundle.noise?.healthy) {
        downloads.push(fetchArtifactFile(selectedBundle.noise).then(file => { files.noiseFile = file; }).catch(err => {
          failures.push(err instanceof Error ? err.message : String(err));
        }));
      }
      await Promise.all(downloads);
      if (files.gpsFile || files.noiseFile) onApplyToSimulation(files);
      setApplyMessage(failures.length > 0 ? failures.join('; ') : '已套用健康資料');
    } finally {
      setApplying(false);
    }
  }, [onApplyToSimulation, selectedBundle]);

  const activeBundleId = selectedBundleId ?? selectedBundle?.mission_id ?? null;
  const selected = bundles.find(bundle => bundle.mission_id === activeBundleId) ?? selectedBundle;

  return (
    <MinPanel
      title="歷史任務清單"
      className="panel-ui trajectory-history-panel"
      defaultMinimized
      actions={
        <>
          <button type="button" className="trajectory-history-panel__icon-btn" onClick={() => void importIncoming()}>
            Import incoming
          </button>
          <button type="button" className="trajectory-history-panel__icon-btn" onClick={() => void refresh()}>
            Refresh
          </button>
        </>
      }
    >
      <PanelGrid>
        <PanelField label="Missions" value={bundles.length} />
        <PanelField label="Selected" value={selected ? selected.mission_id : '-'} />
      </PanelGrid>

      {status === 'error' && <PanelEmpty>{error}</PanelEmpty>}
      {bundles.length === 0 && status !== 'loading' && <PanelEmpty>No mission bundles found.</PanelEmpty>}
      {status === 'loading' && <PanelStatus label="Loading" tone="waiting" />}

      <div className="trajectory-history-panel__list">
        {bundles.map(bundle => {
          const active = bundle.mission_id === activeBundleId || bundle.mission_id === selectedEventId;
          const labels = labelsFor(bundle);
          return (
            <button
              key={bundle.mission_id}
              type="button"
              className={`trajectory-history-panel__item${active ? ' is-active' : ''}`}
              onClick={() => void selectBundle(bundle.mission_id)}
            >
              <span className="trajectory-history-panel__item-title">
                {bundle.mission_id}
              </span>
              <span className="trajectory-history-panel__item-meta">
                {labels.map(label => (
                  <span
                    key={label}
                    style={{
                      color: label === '[N/A]' ? 'rgba(255,255,255,.4)' : '#67e8f9',
                      marginRight: 6,
                    }}
                  >
                    {label}
                  </span>
                ))}
                {bundle.metadata_only && <span>metadata-only</span>}
              </span>
              <span className="trajectory-history-panel__item-meta">
                {formatDate(bundle.updated_at)}
              </span>
            </button>
          );
        })}
      </div>

      <PanelFooter>
        <button type="button" className="trajectory-history-panel__link-btn" onClick={() => onSelectEvent(null)}>
          Clear overlay
        </button>
        {selected && onApplyToSimulation && (
          <button
            type="button"
            className="trajectory-history-panel__link-btn"
            onClick={() => void applyToSimulation()}
            disabled={applying || (!selected.gps?.healthy && !selected.noise?.healthy)}
          >
            {applying ? '套用中…' : '套用至模擬'}
          </button>
        )}
        <span>{applyMessage || (selected ? selected.mission_id : 'No overlay')}</span>
      </PanelFooter>
    </MinPanel>
  );
}
