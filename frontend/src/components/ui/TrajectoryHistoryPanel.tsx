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

interface ArtifactBadge {
  key: string;
  label: string;
  tone: 'healthy' | 'invalid' | 'missing';
}

function getSingleArtifactBadge(key: 'gps' | 'noise', artifact?: MissionBundleArtifact | null): ArtifactBadge {
  const name = key === 'gps' ? 'GPS' : 'NOISE';
  if (artifact?.healthy) {
    return { key, label: `[${name}]`, tone: 'healthy' };
  }
  if (artifact?.exists) {
    return { key, label: `[${name} 無效]`, tone: 'invalid' };
  }
  return { key, label: `[無 ${name}]`, tone: 'missing' };
}

function artifactBadges(bundle: MissionBundle): ArtifactBadge[] {
  return [
    getSingleArtifactBadge('gps', bundle.gps),
    getSingleArtifactBadge('noise', bundle.noise),
  ];
}

function badgeColor(tone: 'healthy' | 'invalid' | 'missing'): string {
  if (tone === 'healthy') return '#67e8f9';
  if (tone === 'invalid') return '#fbbf24';
  return 'rgba(255, 255, 255, 0.4)';
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
  const [minimized, setMinimized] = useState(true);
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
      setMinimized(false);
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

  const sortedBundles = [...bundles].sort((a, b) => {
    const timeA = a.updated_at ? new Date(a.updated_at).getTime() : 0;
    const timeB = b.updated_at ? new Date(b.updated_at).getTime() : 0;
    return timeB - timeA;
  });

  const activeBundleId = selectedBundleId ?? selectedBundle?.mission_id ?? null;
  const selected = bundles.find(bundle => bundle.mission_id === activeBundleId) ?? selectedBundle;

  return (
    <MinPanel
      title="歷史任務清單"
      className="panel-ui trajectory-history-panel"
      minimized={minimized}
      onMinimizedChange={setMinimized}
      actions={
        <>
          <button
            type="button"
            className="trajectory-history-panel__icon-btn"
            aria-label="Import incoming"
            onClick={() => void importIncoming()}
          >
            匯入傳入任務
          </button>
          <button
            type="button"
            className="trajectory-history-panel__icon-btn"
            aria-label="Refresh"
            onClick={() => void refresh()}
          >
            重新整理
          </button>
        </>
      }
    >
      <PanelGrid>
        <PanelField label="任務總數" value={bundles.length} />
        <PanelField label="目前選取" value={selected ? selected.mission_id : '-'} />
      </PanelGrid>

      {status === 'error' && <PanelEmpty>{error}</PanelEmpty>}
      {bundles.length === 0 && status !== 'loading' && <PanelEmpty>未找到歷史任務包。</PanelEmpty>}
      {status === 'loading' && <PanelStatus label="Loading" tone="waiting" />}

      <div className="trajectory-history-panel__list">
        {sortedBundles.map(bundle => {
          const active = bundle.mission_id === activeBundleId || bundle.mission_id === selectedEventId;
          const badges = artifactBadges(bundle);
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
                {badges.map(badge => (
                  <span
                    key={badge.key}
                    style={{
                      color: badgeColor(badge.tone),
                      marginRight: 6,
                      fontWeight: 600,
                    }}
                  >
                    {badge.label}
                  </span>
                ))}
              </span>
              <span className="trajectory-history-panel__item-meta">
                {formatDate(bundle.updated_at)}
              </span>
            </button>
          );
        })}
      </div>

      {selected && (
        <div style={{ padding: '8px', background: 'rgba(0,0,0,0.2)', borderRadius: '6px', fontSize: '11px', marginTop: '8px', display: 'flex', flexDirection: 'column', gap: '4px' }}>
          <div><strong>已選取任務：</strong>{selected.mission_id}</div>
          <div>
            <strong>GPS: </strong>
            <span style={{ color: selected.gps?.healthy ? '#67e8f9' : selected.gps?.exists ? '#fbbf24' : 'rgba(255,255,255,.4)' }}>
              {selected.gps?.healthy ? '有效' : selected.gps?.exists ? '異常' : '缺少'}
            </span>
            {' · '}
            <strong>Noise: </strong>
            <span style={{ color: selected.noise?.healthy ? '#67e8f9' : selected.noise?.exists ? '#fbbf24' : 'rgba(255,255,255,.4)' }}>
              {selected.noise?.healthy ? '有效' : selected.noise?.exists ? '異常' : '缺少'}
            </span>
          </div>
          <div>
            <strong>軌跡預覽：</strong>
            <span>{selectedEventId === selected.mission_id ? 'GPS 軌跡預覽中' : '未預覽軌跡'}</span>
          </div>
        </div>
      )}

      <PanelFooter>
        <button type="button" className="trajectory-history-panel__link-btn" aria-label="Clear overlay" onClick={() => onSelectEvent(null)}>
          清除軌跡
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
        <span>{applyMessage || (selected ? selected.mission_id : '未套用資料')}</span>
      </PanelFooter>
    </MinPanel>
  );
}
