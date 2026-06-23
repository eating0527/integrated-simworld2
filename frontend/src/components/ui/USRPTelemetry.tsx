import { useCallback, useEffect, useState } from 'react';
import type React from 'react';
import type { USRPSpectrumEvent } from '@/hooks/useGPSSync';
import { MinPanel } from './MinPanel';

const API = import.meta.env.VITE_API_URL || '';

interface Props {
  event?: USRPSpectrumEvent | null;
}

type SamplingMode = 'test' | 'usrp';
type ServiceState = 'running' | 'stopped' | 'unknown';

interface SamplingStatus {
  success: boolean;
  raspi_connected: boolean;
  session_connected: boolean;
  mode: SamplingMode;
  service_name: string;
  service_state: ServiceState;
  message: string;
  service_messages: string[];
}

const MODE_LABELS: Record<SamplingMode, string> = {
  test: '測試模式',
  usrp: 'USRP 模式',
};

const MODE_SERVICE_NAMES: Record<SamplingMode, string> = {
  test: 'drone_test.service',
  usrp: 'drone.service',
};

function ageSeconds(event?: USRPSpectrumEvent | null): number | null {
  if (!event?.timestamp) return null;
  return Math.max(0, Math.round(Date.now() / 1000 - event.timestamp));
}

function raspiLabel(status: SamplingStatus | null, busy: boolean): string {
  if (busy && !status) return '檢查中';
  if (!status) return '檢查中';
  return status.raspi_connected || status.session_connected ? '已連線' : '未連線';
}

function serviceLabel(status: SamplingStatus | null): string {
  if (!status) return '狀態未知';
  if (status.service_state === 'running') return '採樣中';
  if (status.service_state === 'stopped') return '已停止';
  return '狀態未知';
}

function normalizeMode(mode: unknown, fallback: SamplingMode): SamplingMode {
  return mode === 'usrp' || mode === 'test' ? mode : fallback;
}

function normalizeStatus(data: Partial<SamplingStatus>, ok: boolean, fallbackMode: SamplingMode): SamplingStatus {
  const mode = normalizeMode(data.mode, fallbackMode);
  return {
    success: Boolean(data.success ?? ok),
    raspi_connected: Boolean(data.raspi_connected),
    session_connected: Boolean(data.session_connected ?? data.raspi_connected),
    mode,
    service_name: String(data.service_name ?? MODE_SERVICE_NAMES[mode]),
    service_state: data.service_state ?? 'unknown',
    message: String(data.message ?? ''),
    service_messages: Array.isArray(data.service_messages)
      ? data.service_messages.map(item => String(item))
      : [],
  };
}

const S: Record<string, React.CSSProperties> = {
  panel: {
    position: 'fixed',
    top: 132,
    left: 276,
    zIndex: 997,
    width: 340,
    background: 'rgba(8, 12, 24, 0.82)',
    border: '1px solid rgba(80, 180, 255, 0.24)',
    borderRadius: 8,
    padding: '12px 14px',
    color: '#e8f2ff',
    boxShadow: '0 10px 30px rgba(0, 0, 0, 0.45)',
    backdropFilter: 'blur(14px)',
    WebkitBackdropFilter: 'blur(14px)',
    fontFamily: "'Segoe UI', system-ui, sans-serif",
    pointerEvents: 'auto',
  },
  header: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: 10,
    marginBottom: 10,
  },
  title: {
    fontSize: 11,
    fontWeight: 700,
    letterSpacing: '0.1em',
    textTransform: 'uppercase',
    color: '#63c7ff',
  },
  pill: {
    display: 'inline-flex',
    alignItems: 'center',
    gap: 6,
    fontSize: 11,
    color: '#b8d8ff',
  },
  dot: {
    width: 8,
    height: 8,
    borderRadius: '50%',
    background: '#00e58a',
    boxShadow: '0 0 10px rgba(0, 229, 138, 0.85)',
  },
  control: {
    marginBottom: 10,
    padding: '9px 10px',
    borderRadius: 6,
    background: 'rgba(255, 255, 255, 0.05)',
    border: '1px solid rgba(120, 180, 255, 0.12)',
  },
  modeSwitch: {
    display: 'grid',
    gridTemplateColumns: '1fr 1fr',
    gap: 6,
    marginBottom: 9,
  },
  statusRows: {
    display: 'grid',
    gridTemplateColumns: '72px 1fr',
    gap: '5px 8px',
    fontSize: 12,
    marginBottom: 8,
  },
  statusKey: {
    color: 'rgba(210, 230, 255, 0.55)',
    fontSize: 10,
    letterSpacing: '0.08em',
    textTransform: 'uppercase',
  },
  statusValue: {
    color: '#ffffff',
    fontWeight: 700,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
  },
  message: {
    marginBottom: 8,
    color: '#b8d8ff',
    fontSize: 11,
    lineHeight: 1.35,
    wordBreak: 'break-word',
  },
  error: {
    marginBottom: 8,
    color: '#ffb0b0',
    fontSize: 11,
    lineHeight: 1.35,
    wordBreak: 'break-word',
  },
  actions: {
    display: 'grid',
    gridTemplateColumns: '1fr 1fr',
    gap: 6,
    marginTop: 6,
  },
  serviceActions: {
    display: 'grid',
    gridTemplateColumns: '1fr 1fr 1fr',
    gap: 6,
    marginTop: 6,
  },
  button: {
    border: '1px solid rgba(140, 205, 255, 0.22)',
    borderRadius: 6,
    background: 'rgba(99, 199, 255, 0.12)',
    color: '#e8f2ff',
    minHeight: 30,
    padding: '0 8px',
    fontSize: 12,
    fontWeight: 700,
    cursor: 'pointer',
  },
  activeButton: {
    background: 'rgba(0, 229, 138, 0.18)',
    borderColor: 'rgba(0, 229, 138, 0.34)',
  },
  stopButton: {
    background: 'rgba(255, 116, 116, 0.14)',
    borderColor: 'rgba(255, 116, 116, 0.26)',
  },
  log: {
    marginTop: 9,
    padding: '8px 9px',
    borderRadius: 6,
    background: 'rgba(0, 0, 0, 0.18)',
    border: '1px solid rgba(255, 255, 255, 0.08)',
    maxHeight: 128,
    overflow: 'auto',
    fontSize: 10,
    lineHeight: 1.45,
    fontFamily: "'Cascadia Mono', Consolas, monospace",
    color: 'rgba(232, 242, 255, 0.78)',
  },
  logLine: {
    minHeight: 14,
  },
  name: {
    fontSize: 15,
    fontWeight: 700,
    marginBottom: 8,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
  },
  grid: {
    display: 'grid',
    gridTemplateColumns: '1fr 1fr',
    gap: 8,
  },
  field: {
    background: 'rgba(255, 255, 255, 0.055)',
    border: '1px solid rgba(255, 255, 255, 0.08)',
    borderRadius: 6,
    padding: '7px 8px',
  },
  label: {
    display: 'block',
    fontSize: 10,
    color: 'rgba(210, 230, 255, 0.58)',
    letterSpacing: '0.08em',
    textTransform: 'uppercase',
    marginBottom: 3,
  },
  value: {
    display: 'block',
    fontSize: 13,
    fontFamily: "'Cascadia Mono', Consolas, monospace",
    color: '#ffffff',
  },
  footer: {
    marginTop: 10,
    paddingTop: 9,
    borderTop: '1px solid rgba(120, 180, 255, 0.12)',
    fontSize: 10,
    color: 'rgba(210, 230, 255, 0.55)',
    fontFamily: "'Cascadia Mono', Consolas, monospace",
  },
  empty: {
    fontSize: 12,
    color: 'rgba(220, 235, 255, 0.68)',
    lineHeight: 1.5,
  },
};

export function USRPTelemetry({ event }: Props) {
  const age = ageSeconds(event);
  const [samplingMode, setSamplingMode] = useState<SamplingMode>('test');
  const [samplingStatus, setSamplingStatus] = useState<SamplingStatus | null>(null);
  const [samplingBusy, setSamplingBusy] = useState(false);

  const requestSampling = useCallback(async (path: string, init?: RequestInit, options?: { withMode?: boolean }) => {
    const withMode = options?.withMode ?? true;
    const requestPath = withMode ? `${path}?mode=${samplingMode}` : path;
    setSamplingBusy(true);
    try {
      const res = init ? await fetch(`${API}${requestPath}`, init) : await fetch(`${API}${requestPath}`);
      const data = await res.json().catch(() => ({}));
      setSamplingStatus(normalizeStatus(data, res.ok, samplingMode));
    } catch (error) {
      setSamplingStatus({
        success: false,
        raspi_connected: false,
        session_connected: false,
        mode: samplingMode,
        service_name: MODE_SERVICE_NAMES[samplingMode],
        service_state: 'unknown',
        message: error instanceof Error ? error.message : 'RasPi request failed',
        service_messages: [],
      });
    } finally {
      setSamplingBusy(false);
    }
  }, [samplingMode]);

  useEffect(() => {
    void requestSampling('/api/usrp/sampling/status');
  }, [requestSampling]);

  const raspiConnected = Boolean(samplingStatus?.raspi_connected || samplingStatus?.session_connected);
  const samplingRunning = samplingStatus?.service_state === 'running';
  const disabledOpacity = (disabled: boolean) => ({ opacity: disabled ? 0.48 : 1 });
  const statusMessage = samplingStatus?.message ?? '';

  const handleModeChange = (mode: SamplingMode) => {
    if (mode === samplingMode || samplingBusy || samplingRunning) return;
    setSamplingStatus(null);
    setSamplingMode(mode);
  };

  return (
    <MinPanel
      title="USRP 設定"
      draggable
      style={S.panel}
      actions={(
        <div style={S.pill}>
          <span style={{ ...S.dot, background: event ? '#00e58a' : '#56657a' }} />
          {event ? 'Live' : 'Waiting'}
        </div>
      )}
    >
      <div style={S.control}>
        <div style={S.modeSwitch} aria-label="USRP 採樣模式">
          {(['test', 'usrp'] as SamplingMode[]).map(mode => {
            const active = samplingMode === mode;
            const disabled = samplingBusy || samplingRunning;
            return (
              <button
                key={mode}
                type="button"
                aria-pressed={active}
                style={{
                  ...S.button,
                  ...(active ? S.activeButton : null),
                  ...disabledOpacity(disabled),
                }}
                disabled={disabled}
                onClick={() => handleModeChange(mode)}
              >
                {MODE_LABELS[mode]}
              </button>
            );
          })}
        </div>

        <div style={S.statusRows}>
          <span style={S.statusKey}>模式</span>
          <span style={S.statusValue}>{MODE_LABELS[samplingMode]}</span>
          <span style={S.statusKey}>RasPi</span>
          <span style={S.statusValue}>{raspiLabel(samplingStatus, samplingBusy)}</span>
          <span style={S.statusKey}>Service</span>
          <span style={S.statusValue}>{serviceLabel(samplingStatus)}</span>
          <span style={S.statusKey}>Unit</span>
          <span style={S.statusValue}>{samplingStatus?.service_name ?? MODE_SERVICE_NAMES[samplingMode]}</span>
        </div>

        {statusMessage ? (
          samplingStatus?.success
            ? <div style={S.message}>{statusMessage}</div>
            : <div role="alert" style={S.error}>{statusMessage}</div>
        ) : null}

        <div style={S.actions}>
          <button
            type="button"
            style={{ ...S.button, ...disabledOpacity(samplingBusy || raspiConnected) }}
            disabled={samplingBusy || raspiConnected}
            onClick={() => void requestSampling('/api/usrp/sampling/connect', { method: 'POST' })}
          >
            連線
          </button>
          <button
            type="button"
            style={{ ...S.button, ...S.stopButton, ...disabledOpacity(samplingBusy || !raspiConnected) }}
            disabled={samplingBusy || !raspiConnected}
            onClick={() => void requestSampling('/api/usrp/sampling/disconnect', { method: 'POST' }, { withMode: false })}
          >
            中斷
          </button>
        </div>

        <div style={S.serviceActions}>
          <button
            type="button"
            style={{ ...S.button, ...disabledOpacity(!raspiConnected || samplingBusy || samplingRunning) }}
            disabled={!raspiConnected || samplingBusy || samplingRunning}
            onClick={() => void requestSampling('/api/usrp/sampling/start', { method: 'POST' })}
          >
            開始採樣
          </button>
          <button
            type="button"
            style={{ ...S.button, ...S.stopButton, ...disabledOpacity(!raspiConnected || samplingBusy) }}
            disabled={!raspiConnected || samplingBusy}
            onClick={() => void requestSampling('/api/usrp/sampling/stop', { method: 'POST' })}
          >
            終止採樣
          </button>
          <button
            type="button"
            style={{ ...S.button, ...disabledOpacity(!raspiConnected || samplingBusy) }}
            disabled={!raspiConnected || samplingBusy}
            onClick={() => void requestSampling('/api/usrp/sampling/messages')}
          >
            更新訊息
          </button>
        </div>

        <div style={S.log} aria-label="service 訊息">
          {samplingStatus?.service_messages.length
            ? samplingStatus.service_messages.map((line, index) => (
              <div key={`${index}-${line}`} style={S.logLine}>{line}</div>
            ))
            : <div style={S.logLine}>尚無 service 訊息</div>}
        </div>
      </div>

      {!event ? (
        <div style={S.empty}>
          Waiting for `usrp-spectrum` events from the B210 bridge.
        </div>
      ) : (
        <>
          <div style={S.name}>{event.deviceName || 'USRP B210 Sensor'}</div>
          <div style={S.grid}>
            <div style={S.field}>
              <span style={S.label}>Center Freq</span>
              <span style={S.value}>{(event.center_freq_hz / 1e6).toFixed(3)} MHz</span>
            </div>
            <div style={S.field}>
              <span style={S.label}>Sample Rate</span>
              <span style={S.value}>{(event.sample_rate_hz / 1e6).toFixed(3)} Msps</span>
            </div>
            <div style={S.field}>
              <span style={S.label}>Mean Power</span>
              <span style={S.value}>{event.mean_power_dbfs.toFixed(2)} dBFS</span>
            </div>
            <div style={S.field}>
              <span style={S.label}>Peak Power</span>
              <span style={S.value}>{event.peak_power_dbfs.toFixed(2)} dBFS</span>
            </div>
            <div style={S.field}>
              <span style={S.label}>Gain</span>
              <span style={S.value}>{event.gain_db.toFixed(1)} dB</span>
            </div>
            <div style={S.field}>
              <span style={S.label}>Samples</span>
              <span style={S.value}>{event.sample_count}</span>
            </div>
          </div>
          <div style={S.footer}>
            {event.deviceId}
            {age !== null ? ` - ${age}s ago` : ''}
          </div>
        </>
      )}
    </MinPanel>
  );
}
