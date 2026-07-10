import { useCallback, useEffect, useMemo, useState } from 'react';
import type React from 'react';
import { MinPanel } from './MinPanel';
import { PanelStatus } from './PanelUi';

const API = import.meta.env.VITE_API_URL || '';

type SamplingMode = 'test' | 'usrp';
type ConnectionState = 'ready' | 'offline' | 'unknown';
type ServiceState = 'idle' | 'starting' | 'running' | 'presumed_running' | 'stopping' | 'stopped' | 'failed';
type FileState = 'none' | 'recording' | 'finalizing' | 'ready' | 'upload_pending' | 'uploaded' | 'failed';

interface ChildState {
  mission_id: string;
  connection: ConnectionState;
  service: ServiceState;
  file: FileState;
  error: string;
  path: string;
  pid: number | null;
}

interface CaptureStatus {
  mission_id: string;
  target: 'uav' | 'usrp' | 'bind';
  bind: boolean;
  selected_usrp_mode: SamplingMode;
  overall_state: string;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  uav: ChildState;
  usrp: ChildState;
}

const EMPTY_CHILD: ChildState = {
  mission_id: '',
  connection: 'unknown',
  service: 'idle',
  file: 'none',
  error: '',
  path: '',
  pid: null,
};

const CONNECTION_LABELS: Record<ConnectionState, string> = {
  ready: 'Ready',
  offline: 'Offline',
  unknown: 'Unknown',
};

const SERVICE_LABELS: Record<ServiceState, string> = {
  idle: 'Idle',
  starting: 'Starting',
  running: 'Running',
  presumed_running: 'Presumed running',
  stopping: 'Stopping',
  stopped: 'Stopped',
  failed: 'Failed',
};

const FILE_LABELS: Record<FileState, string> = {
  none: 'None',
  recording: 'Recording',
  finalizing: 'Finalizing',
  ready: 'Ready',
  upload_pending: 'Pending upload',
  uploaded: 'Uploaded',
  failed: 'Failed',
};

const S: Record<string, React.CSSProperties> = {
  control: {
    marginBottom: 10,
    padding: '10px',
    borderRadius: 6,
    background: 'rgba(255, 255, 255, 0.05)',
    border: '1px solid rgba(120, 180, 255, 0.12)',
  },
  topRow: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: 8,
    marginBottom: 10,
  },
  section: {
    padding: '9px',
    marginTop: 8,
    borderRadius: 6,
    background: 'rgba(0, 0, 0, 0.16)',
  },
  sectionTitle: {
    marginBottom: 7,
    color: '#ffffff',
    fontSize: 12,
    fontWeight: 800,
  },
  rows: {
    display: 'grid',
    gridTemplateColumns: '76px 1fr',
    gap: '4px 8px',
    fontSize: 11,
  },
  key: {
    color: 'rgba(210, 230, 255, 0.55)',
    textTransform: 'uppercase',
    letterSpacing: '0.06em',
  },
  value: {
    color: '#e8f2ff',
    fontWeight: 700,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
  },
  actions: {
    display: 'grid',
    gridTemplateColumns: '1fr 1fr',
    gap: 6,
    marginTop: 8,
  },
  modes: {
    display: 'grid',
    gridTemplateColumns: '1fr 1fr',
    gap: 6,
    marginTop: 8,
  },
  button: {
    minHeight: 30,
    padding: '0 8px',
    border: '1px solid rgba(140, 205, 255, 0.22)',
    borderRadius: 6,
    background: 'rgba(99, 199, 255, 0.12)',
    color: '#e8f2ff',
    fontSize: 11,
    fontWeight: 700,
    cursor: 'pointer',
  },
  active: {
    background: 'rgba(0, 229, 138, 0.18)',
    borderColor: 'rgba(0, 229, 138, 0.34)',
  },
  stop: {
    background: 'rgba(255, 116, 116, 0.14)',
    borderColor: 'rgba(255, 116, 116, 0.26)',
  },
  error: {
    marginTop: 8,
    color: '#ffb0b0',
    fontSize: 11,
    lineHeight: 1.35,
  },
  mission: {
    marginTop: 8,
    color: 'rgba(210, 230, 255, 0.65)',
    fontSize: 10,
    wordBreak: 'break-all',
  },
  name: {
    marginBottom: 8,
    color: '#ffffff',
    fontSize: 15,
    fontWeight: 700,
  },
};

function isActive(service: ServiceState): boolean {
  return ['starting', 'running', 'presumed_running', 'stopping'].includes(service);
}

function canStop(service: ServiceState): boolean {
  return ['starting', 'running', 'presumed_running'].includes(service);
}

function normalizeStatus(value: Partial<CaptureStatus>): CaptureStatus {
  return {
    mission_id: String(value.mission_id ?? ''),
    target: value.target === 'usrp' || value.target === 'bind' ? value.target : 'uav',
    bind: Boolean(value.bind),
    selected_usrp_mode: value.selected_usrp_mode === 'usrp' ? 'usrp' : 'test',
    overall_state: String(value.overall_state ?? 'ready'),
    created_at: String(value.created_at ?? ''),
    started_at: value.started_at ?? null,
    finished_at: value.finished_at ?? null,
    uav: { ...EMPTY_CHILD, ...(value.uav ?? {}) },
    usrp: { ...EMPTY_CHILD, ...(value.usrp ?? {}) },
  };
}

function responseMessage(value: unknown, fallback: string): string {
  if (value && typeof value === 'object') {
    const body = value as { detail?: unknown; error?: unknown };
    if (typeof body.detail === 'string') return body.detail;
    if (typeof body.error === 'string') return body.error;
  }
  return fallback;
}

async function readCaptureResponse(response: Response, fallback: string): Promise<Partial<CaptureStatus>> {
  const raw = await response.text();
  let data: unknown = {};
  if (raw) {
    try {
      data = JSON.parse(raw);
    } catch (parseError) {
      if (!response.ok) throw new Error(raw);
      throw parseError;
    }
  }
  if (!response.ok) throw new Error(responseMessage(data, raw || fallback));
  return data as Partial<CaptureStatus>;
}

export function USRPTelemetry() {
  const [mode, setMode] = useState<SamplingMode>('test');
  const [bind, setBind] = useState(false);
  const [status, setStatus] = useState<CaptureStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const applyStatus = useCallback((data: Partial<CaptureStatus>) => {
    const next = normalizeStatus(data);
    setStatus(next);
    if (next.bind && (isActive(next.uav.service) || isActive(next.usrp.service))) {
      setBind(true);
    }
    if (isActive(next.usrp.service)) {
      setMode(next.selected_usrp_mode);
    }
  }, []);

  const loadStatus = useCallback(async () => {
    try {
      const response = await fetch(`${API}/api/capture/status?usrp_mode=${mode}`);
      const data = await readCaptureResponse(response, 'Status request failed');
      applyStatus(data);
      setError('');
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : 'Status request failed');
    }
  }, [applyStatus, mode]);

  useEffect(() => {
    void loadStatus();
  }, [loadStatus]);

  const shouldPoll = Boolean(
    status && (
      isActive(status.uav.service) ||
      isActive(status.usrp.service) ||
      ['finalizing', 'upload_pending'].includes(status.uav.file) ||
      ['finalizing', 'upload_pending'].includes(status.usrp.file)
    )
  );

  useEffect(() => {
    if (!shouldPoll) return;
    const timer = window.setInterval(() => void loadStatus(), 2000);
    return () => window.clearInterval(timer);
  }, [loadStatus, shouldPoll]);

  const request = useCallback(async (path: string, body?: object) => {
    setBusy(true);
    setError('');
    try {
      const response = await fetch(`${API}${path}`, {
        method: 'POST',
        ...(body
          ? { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }
          : {}),
      });
      const data = await readCaptureResponse(response, 'Capture request failed');
      applyStatus(data);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : 'Capture request failed');
    } finally {
      setBusy(false);
    }
  }, [applyStatus]);

  const startBody = useMemo(
    () => ({ usrp_mode: mode, scene: 'NTPU', map_type: 'iss' }),
    [mode],
  );
  const uav = status?.uav ?? EMPTY_CHILD;
  const usrp = status?.usrp ?? EMPTY_CHILD;
  const missionId = status?.mission_id ?? '';
  const uavMissionId = uav.mission_id || missionId;
  const usrpMissionId = usrp.mission_id || missionId;
  const anyActive = isActive(uav.service) || isActive(usrp.service);
  const bothReady = uav.connection === 'ready' && usrp.connection === 'ready';
  const disabledStyle = (disabled: boolean) => ({ opacity: disabled ? 0.45 : 1 });

  const childSection = (
    title: string,
    child: ChildState,
    actions: React.ReactNode,
  ) => (
    <section style={S.section}>
      <div style={S.sectionTitle}>{title}</div>
      <div style={S.rows}>
        <span style={S.key}>Connection</span>
        <span style={S.value}>{CONNECTION_LABELS[child.connection]}</span>
        <span style={S.key}>Service</span>
        <span style={S.value}>{SERVICE_LABELS[child.service]}</span>
        <span style={S.key}>File</span>
        <span style={S.value}>{FILE_LABELS[child.file]}</span>
      </div>
      {child.error ? <div role="alert" style={S.error}>{child.error}</div> : null}
      {actions}
    </section>
  );

  return (
    <MinPanel
      title="採樣控制面板"
      className="panel-ui"
      defaultMinimized
      actions={<PanelStatus tone={anyActive ? 'live' : 'waiting'} label={anyActive ? 'Active' : 'Ready'} />}
    >
      <div style={S.control}>
        <div style={S.topRow}>
          <strong>裝置綁定</strong>
          <button
            type="button"
            role="switch"
            aria-label="Bind services"
            aria-checked={bind}
            disabled={busy || anyActive}
            style={{ ...S.button, ...(bind ? S.active : null), ...disabledStyle(busy || anyActive) }}
            onClick={() => setBind(value => !value)}
          >
            {bind ? '啟用' : '關閉'}
          </button>
        </div>

        {childSection(
          '無人機 GPS 採樣',
          uav,
          <div style={S.actions}>
            <button
              type="button"
              style={{ ...S.button, ...disabledStyle(bind || busy || isActive(uav.service) || uav.connection !== 'ready') }}
              disabled={bind || busy || isActive(uav.service) || uav.connection !== 'ready'}
              onClick={() => void request('/api/capture/uav/start')}
            >
              Start UAV
            </button>
            <button
              type="button"
              style={{ ...S.button, ...S.stop, ...disabledStyle(busy || !canStop(uav.service)) }}
              disabled={busy || !canStop(uav.service)}
              onClick={() => void request(`/api/capture/uav/stop?mission_id=${encodeURIComponent(uavMissionId)}`)}
            >
              Stop UAV
            </button>
          </div>,
        )}

        {childSection(
          'USRP 干擾採樣',
          usrp,
          <>
            <div style={S.modes} aria-label="USRP capture mode">
              {(['test', 'usrp'] as SamplingMode[]).map(value => (
                <button
                  key={value}
                  type="button"
                  aria-label={value === 'test' ? 'Test mode' : 'USRP mode'}
                  aria-pressed={mode === value}
                  disabled={busy || isActive(usrp.service)}
                  style={{
                    ...S.button,
                    ...(mode === value ? S.active : null),
                    ...disabledStyle(busy || isActive(usrp.service)),
                  }}
                  onClick={() => setMode(value)}
                >
                  {value === 'test' ? 'Test' : 'USRP'}
                </button>
              ))}
            </div>
            <div style={S.actions}>
              <button
                type="button"
                style={{ ...S.button, ...disabledStyle(bind || busy || isActive(usrp.service) || usrp.connection !== 'ready') }}
                disabled={bind || busy || isActive(usrp.service) || usrp.connection !== 'ready'}
                onClick={() => void request('/api/capture/usrp/start', startBody)}
              >
                Start USRP
              </button>
              <button
                type="button"
                style={{ ...S.button, ...S.stop, ...disabledStyle(busy || !canStop(usrp.service)) }}
                disabled={busy || !canStop(usrp.service)}
                onClick={() => void request(`/api/capture/usrp/stop?mission_id=${encodeURIComponent(usrpMissionId)}`)}
              >
                Stop USRP
              </button>
            </div>
          </>,
        )}

        {bind ? (
          <div style={S.actions}>
            <button
              type="button"
              style={{ ...S.button, ...S.active, ...disabledStyle(busy || anyActive || !bothReady) }}
              disabled={busy || anyActive || !bothReady}
              onClick={() => void request('/api/capture/bind/start', startBody)}
            >
              Start Bound Capture
            </button>
            <button
              type="button"
              style={{ ...S.button, ...S.stop, ...disabledStyle(busy || !missionId || !anyActive) }}
              disabled={busy || !missionId || !anyActive}
              onClick={() => void request(`/api/capture/bind/stop?mission_id=${encodeURIComponent(missionId)}`)}
            >
              Stop All
            </button>
          </div>
        ) : null}

        {missionId ? <div style={S.mission}>Mission: {missionId} · {status?.overall_state}</div> : null}
        {error ? <div role="alert" style={S.error}>{error}</div> : null}
      </div>

    </MinPanel>
  );
}
