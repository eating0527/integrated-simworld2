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
  const date = parseDate(value);
  if (Number.isNaN(date.getTime())) return String(value);
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: 'Asia/Taipei',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hourCycle: 'h23',
  }).formatToParts(date);
  const part = (type: Intl.DateTimeFormatPartTypes) => parts.find(item => item.type === type)?.value ?? '00';
  return `${part('month')}/${part('day')} ${part('hour')}:${part('minute')}:${part('second')}`;
}

function parseDate(value?: string | number | null): Date {
  if (typeof value === 'number') return new Date(value * 1000);
  if (!value) return new Date(Number.NaN);
  const text = value.trim();
  const isNaiveIso = /^\d{4}-\d{2}-\d{2}T/.test(text)
    && !/(?:Z|[+-]\d{2}:?\d{2})$/i.test(text);
  return new Date(isNaiveIso ? `${text}+08:00` : text);
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
  if (!bundle.gps?.exists && !bundle.noise?.exists) {
    return [{ key: 'none', label: '[N/A]', tone: 'missing' }];
  }
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

function payloadError(payload: unknown): string | null {
  if (!payload || typeof payload !== 'object') return null;
  const value = payload as { detail?: unknown; errors?: unknown };
  if (typeof value.detail === 'string') return value.detail;
  if (Array.isArray(value.errors)) {
    const messages = value.errors
      .map(error => {
        if (typeof error === 'string') return error;
        if (error && typeof error === 'object' && 'error' in error && typeof error.error === 'string') {
          return error.error;
        }
        return null;
      })
      .filter((message): message is string => Boolean(message));
    if (messages.length > 0) return messages.join('、');
  }
  return null;
}

function hasFailed(payload: unknown): boolean {
  return Boolean(payload && typeof payload === 'object' && 'success' in payload && payload.success === false);
}

function requestError(action: string, res: Response, payload?: unknown): Error {
  const detail = payloadError(payload);
  const suffix = detail ? `：${detail}` : res.status ? `（${res.status}）` : '';
  return new Error(`${action}失敗${suffix}`);
}

async function readPayload(res: Response): Promise<unknown> {
  try {
    return await res.json();
  } catch {
    return null;
  }
}

interface BundleListResult {
  bundles: MissionBundle[];
  warning: string | null;
}

async function fetchBundles(): Promise<BundleListResult> {
  const res = await fetch(`${API}/api/mission-bundles`);
  const payload = await readPayload(res);
  const value = payload && typeof payload === 'object'
    ? payload as { bundles?: unknown; missions?: unknown }
    : {};
  const bundles = Array.isArray(value.bundles)
    ? value.bundles as MissionBundle[]
    : Array.isArray(value.missions) ? value.missions as MissionBundle[] : [];
  if (!res.ok || (hasFailed(payload) && bundles.length === 0)) {
    throw requestError('讀取歷史任務', res, payload);
  }
  return {
    bundles,
    warning: hasFailed(payload) ? requestError('讀取歷史任務', res, payload).message : null,
  };
}

async function fetchBundle(id: string): Promise<MissionBundle> {
  const res = await fetch(`${API}/api/mission-bundles/${encodeURIComponent(id)}`);
  const payload = await readPayload(res);
  if (!res.ok || hasFailed(payload)) throw requestError('讀取歷史任務', res, payload);
  const value = payload && typeof payload === 'object' && 'bundle' in payload
    ? payload.bundle
    : payload;
  return value as MissionBundle;
}

async function importBundles(): Promise<void> {
  const res = await fetch(`${API}/api/mission-bundles/import`, { method: 'POST' });
  const payload = await readPayload(res);
  if (!res.ok || hasFailed(payload)) throw requestError('匯入傳入任務', res, payload);
}

function artifactFetchUrl(url: string): string {
  // The URL is supplied by the backend.  Restrict it to the CSV artifact API
  // before concatenating VITE_API_URL so an imported metadata value cannot turn
  // the Apply action into an arbitrary browser fetch.
  const match = /^\/api\/mission-bundles\/([A-Za-z0-9_.-]+)\/artifacts\/(?:gps|noise)$/.exec(url);
  if (!match || match[1] === '.' || match[1] === '..') {
    throw new Error('任務資料網址無效');
  }
  return `${API}${url}`;
}

async function fetchArtifactFile(artifact: MissionBundleArtifact): Promise<File> {
  if (!artifact.url || !artifact.healthy) throw new Error(`${artifact.kind === 'gps' ? 'GPS' : 'Noise'} 資料不可用`);
  const res = await fetch(artifactFetchUrl(artifact.url));
  if (!res.ok) throw new Error(`無法下載 ${artifact.filename}（${res.status}）`);
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
  const [warning, setWarning] = useState<string | null>(null);
  const [applying, setApplying] = useState(false);
  const [applyMessage, setApplyMessage] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setStatus('loading');
    setError(null);
    setWarning(null);
    try {
      const next = await fetchBundles();
      setBundles(next.bundles);
      setWarning(next.warning);
      setStatus('idle');
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setWarning(null);
      setStatus('error');
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const activeBundleId = selectedBundleId ?? selectedBundle?.mission_id ?? null;
  const selected = activeBundleId
    ? selectedBundle?.mission_id === activeBundleId
      ? selectedBundle
      : bundles.find(bundle => bundle.mission_id === activeBundleId) ?? null
    : selectedBundle;

  const selectBundle = useCallback(async (id: string) => {
    setStatus('loading');
    setError(null);
    setWarning(null);
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
      setWarning(null);
      setStatus('error');
    }
  }, [onSelectEvent]);

  const importIncoming = useCallback(async () => {
    setStatus('loading');
    setError(null);
    try {
      await importBundles();
      const next = await fetchBundles();
      setBundles(next.bundles);
      setWarning(next.warning);
      setStatus('idle');
      setMinimized(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setStatus('error');
    }
  }, []);

  const applyToSimulation = useCallback(async () => {
    if (!selected || !onApplyToSimulation) return;
    setApplying(true);
    setApplyMessage(null);
    const files: { missionId: string; gpsFile?: File; noiseFile?: File } = {
      missionId: selected.mission_id,
    };
    const failures: string[] = [];
    try {
      const downloads: Array<Promise<void>> = [];
      if (selected.gps?.healthy) {
        downloads.push(Promise.resolve()
          .then(() => fetchArtifactFile(selected.gps!))
          .then(file => { files.gpsFile = file; })
          .catch(err => {
            failures.push(err instanceof Error ? err.message : String(err));
          }));
      }
      if (selected.noise?.healthy) {
        downloads.push(Promise.resolve()
          .then(() => fetchArtifactFile(selected.noise!))
          .then(file => { files.noiseFile = file; })
          .catch(err => {
            failures.push(err instanceof Error ? err.message : String(err));
          }));
      }
      await Promise.all(downloads);
      if (files.gpsFile || files.noiseFile) onApplyToSimulation(files);
      setApplyMessage(failures.length > 0 ? `套用資料失敗：${failures.join('；')}` : '已套用健康資料');
    } finally {
      setApplying(false);
    }
  }, [onApplyToSimulation, selected]);

  const sortedBundles = [...bundles].sort((a, b) => {
    const timeA = parseDate(a.updated_at).getTime() || 0;
    const timeB = parseDate(b.updated_at).getTime() || 0;
    return timeB - timeA;
  });

  const isPreviewing = Boolean(selected?.trajectory?.id && selected.trajectory.id === selectedEventId);

  return (
    <MinPanel
      title="歷史任務清單"
      className="panel-ui trajectory-history-panel"
      minimized={minimized}
      onMinimizedChange={setMinimized}
      toggleLabel={(isMinimized) => `${isMinimized ? '展開' : '收合'} 歷史任務清單`}
      showActionsWhenMinimized
      actions={
        <>
          <button
            type="button"
            className="trajectory-history-panel__icon-btn"
            aria-label="匯入傳入任務"
            onClick={() => void importIncoming()}
          >
            匯入傳入任務
          </button>
          <button
            type="button"
            className="trajectory-history-panel__icon-btn"
            aria-label="重新整理歷史任務"
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
      {warning && <div role="status"><PanelStatus label={warning} tone="warning" /></div>}
      {bundles.length === 0 && status !== 'loading' && <PanelEmpty>未找到歷史任務包。</PanelEmpty>}
      {status === 'loading' && <PanelStatus label="載入中" tone="waiting" />}

      <div className="trajectory-history-panel__list">
        {sortedBundles.map(bundle => {
          const active = bundle.mission_id === activeBundleId
            || bundle.trajectory?.id === selectedEventId
            || (selectedBundle?.mission_id === bundle.mission_id && selectedBundle.trajectory?.id === selectedEventId);
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
            <span>{isPreviewing ? 'GPS 軌跡預覽中' : '未預覽軌跡'}</span>
          </div>
        </div>
      )}

      <PanelFooter>
        <button type="button" className="trajectory-history-panel__link-btn" aria-label="清除軌跡" onClick={() => onSelectEvent(null)}>
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
