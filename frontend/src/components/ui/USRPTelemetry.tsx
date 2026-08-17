import { useCallback, useEffect, useId, useMemo, useRef, useState } from 'react';
import type React from 'react';
import { MinPanel } from './MinPanel';
import { PanelStatus } from './PanelUi';

const API = import.meta.env.VITE_API_URL || '';

type SamplingMode = 'test' | 'usrp';
type ConnectionState = 'ready' | 'offline' | 'unknown';
type ServiceState = 'idle' | 'starting' | 'running' | 'presumed_running' | 'stopping' | 'stopped' | 'failed';
type FileState = 'none' | 'recording' | 'finalizing' | 'ready' | 'upload_pending' | 'uploaded' | 'failed';
type ServiceDisplay = ServiceState | 'unknown';
type FileDisplay = FileState | 'unknown';
type OverallState = 'ready' | 'starting' | 'running' | 'degraded' | 'stopping' | 'finalizing' | 'completed' | 'completed_with_warning' | 'failed';
type DisplayState = OverallState | 'unknown';
type CapturePhase = 'idle' | 'preflight' | 'connecting' | 'configuring' | 'starting_service' | 'recording' | 'stopping' | 'stopping_service' | 'finalizing_file' | 'upload_pending' | 'uploading' | 'completed' | 'stopped' | 'reconciling' | 'stop_failed' | 'resume_timeout' | 'failed';
type PhaseDisplay = CapturePhase | 'unknown';

interface ChildState {
  mission_id: string;
  connection: ConnectionState;
  service: ServiceDisplay;
  file: FileDisplay;
  error: string;
  path: string;
  pid: number | null;
  phase?: PhaseDisplay;
  last_sample_at?: string | null;
  disconnected_at?: string | null;
  resume_deadline_at?: string | null;
  upload_state?: string;
  upload_mode?: string;
  upload_started_at?: string | null;
  upload_retry_mode?: string;
  upload_retry_state?: string;
  upload_retry_attempt?: number;
  upload_retry_max_attempts?: number;
  upload_retry_next_attempt_at?: string | null;
  upload_retry_active_started_at?: string | null;
  upload_retry_last_error?: string;
  upload_job_id?: string | null;
  upload_finished_at?: string | null;
}

interface DeviceHealth {
  device: 'ap3' | 'raspi';
  state: ConnectionState;
  checked_at: string;
  last_checked_at: string;
  next_check_at: string | null;
  retry_delay: number | null;
  stale: boolean;
  error: string;
}

interface CaptureStatus {
  mission_id: string;
  target: 'uav' | 'usrp' | 'bind';
  bind: boolean;
  selected_usrp_mode: SamplingMode;
  overall_state: DisplayState;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  stop_requested_at: string | null;
  uav: ChildState;
  usrp: ChildState;
  device_health?: Record<string, DeviceHealth>;
  control_mode?: 'bound' | 'independent';
  active?: Partial<CaptureStatus> | null;
  history?: {
    gps?: MissionSummary | null;
    noise?: MissionSummary | null;
  };
}

interface MissionSummary {
  started_at: string;
  mission_id: string;
}

type DeviceErrorMap = Record<string, string>;

interface CaptureDeviceError {
  device?: unknown;
  error?: unknown;
}

interface CapturePreflightErrorBody {
  error_type?: string;
  message?: string;
  errors?: DeviceErrorMap;
  preflight_errors?: DeviceErrorMap;
  conflicts?: DeviceErrorMap;
  devices?: DeviceErrorMap | CaptureDeviceError[];
}

interface CaptureErrorBody {
  detail?: string | CapturePreflightErrorBody;
  error?: string;
  errors?: DeviceErrorMap;
  preflight_errors?: DeviceErrorMap;
}

const EMPTY_CHILD: ChildState = {
  mission_id: '',
  connection: 'unknown',
  service: 'idle',
  file: 'none',
  error: '',
  path: '',
  pid: null,
  phase: 'idle',
};

const PHASE_LABELS: Record<PhaseDisplay, string> = {
  idle: '閒置', preflight: '前置檢查', connecting: '連線中', configuring: '設定中',
  starting_service: '啟動服務中', recording: '錄製中', stopping_service: '停止服務中',
  finalizing_file: '整理 CSV 中', upload_pending: '等待上傳', uploading: '上傳中',
  stopping: '停止中', completed: '已完成', stopped: '已停止',
  reconciling: '同步推定狀態中', stop_failed: '停止失敗',
  resume_timeout: '恢復逾時', failed: '失敗', unknown: '未知',
};

const CONNECTION_LABELS: Record<ConnectionState, string> = {
  ready: '就緒',
  offline: '離線',
  unknown: '未知',
};

const SERVICE_LABELS: Record<ServiceDisplay, string> = {
  idle: '閒置',
  starting: '啟動中',
  running: '執行中',
  presumed_running: '推定執行中',
  stopping: '停止中',
  stopped: '已停止',
  failed: '失敗',
  unknown: '未知',
};

const FILE_LABELS: Record<FileDisplay, string> = {
  none: '無檔案',
  recording: '錄製中',
  finalizing: '整理中',
  ready: '可用',
  upload_pending: '等待上傳',
  uploaded: '已上傳',
  failed: '失敗',
  unknown: '未知',
};

const OVERALL_STATES = new Set<OverallState>([
  'ready', 'starting', 'running', 'degraded', 'stopping', 'finalizing',
  'completed', 'completed_with_warning', 'failed',
]);

const OVERALL_LABELS: Record<DisplayState, string> = {
  ready: '就緒', starting: '啟動中', running: '執行中', degraded: '狀態異常',
  stopping: '停止中', finalizing: '整理中', completed: '已完成',
  completed_with_warning: '已完成（有注意事項）', failed: '失敗', unknown: '未知',
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
    minHeight: 34,
    padding: '0 8px',
    borderWidth: 1,
    borderStyle: 'solid',
    borderColor: 'rgba(140, 205, 255, 0.22)',
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
  primary: {
    minHeight: 40,
  },
  error: {
    marginTop: 8,
    color: '#ffb0b0',
    fontSize: 11,
    lineHeight: 1.35,
  },
  blocker: {
    marginTop: 6,
    color: '#fbbf24',
    fontSize: 11,
    lineHeight: 1.35,
    gridColumn: '1 / -1',
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
  steps: {
    display: 'grid',
    gap: 3,
    marginTop: 8,
    fontSize: 10,
  },
  health: {
    display: 'grid',
    gridTemplateColumns: 'minmax(0, 1fr) minmax(0, 1fr)',
    gap: 6,
    marginTop: 8,
  },
  healthCard: {
    minWidth: 0,
    padding: '7px',
    borderRadius: 5,
    background: 'rgba(0, 0, 0, 0.2)',
    border: '1px solid rgba(120, 180, 255, 0.12)',
    fontSize: 11,
    overflowWrap: 'anywhere',
    wordBreak: 'break-word',
  },
};

function isActive(service: ServiceDisplay): boolean {
  return ['starting', 'running', 'presumed_running', 'stopping'].includes(service);
}

function isUnresolved(child: ChildState): boolean {
  return isActive(child.service)
    || ['finalizing', 'upload_pending'].includes(child.file)
    || ['stopping', 'stopping_service', 'finalizing_file', 'upload_pending', 'uploading', 'reconciling', 'stop_failed'].includes(child.phase ?? 'idle')
    || child.upload_state === 'running'
    || ['waiting', 'running'].includes(child.upload_retry_state ?? '');
}

function modeBlocker(bind: boolean, status: CaptureStatus | null): string | null {
  if (!status) return null;
  const gpsUnresolved = isUnresolved(status.uav);
  const noiseUnresolved = isUnresolved(status.usrp);
  if (bind || status.bind) {
    return gpsUnresolved || noiseUnresolved ? '請先停止當前任務。' : null;
  }
  if (!gpsUnresolved && !noiseUnresolved) return null;
  const noiseUploading = status.usrp.file === 'upload_pending'
    || status.usrp.upload_state === 'running'
    || ['upload_pending', 'uploading'].includes(status.usrp.phase ?? '')
    || ['waiting', 'running'].includes(status.usrp.upload_retry_state ?? '');
  if (gpsUnresolved && noiseUnresolved) return '請先停止 GPS 與 Noise 任務。';
  if (gpsUnresolved) return '請先停止 GPS 任務。';
  return noiseUploading ? '請先等待 Noise 上傳。' : '請先停止 Noise 任務。';
}

function isPollingPhase(phase?: PhaseDisplay): boolean {
  return Boolean(phase && [
    'preflight', 'connecting', 'configuring', 'starting_service', 'recording',
    'stopping', 'stopping_service', 'finalizing_file', 'upload_pending',
    'uploading', 'reconciling', 'stop_failed',
  ].includes(phase));
}

const STEP_PHASES: Record<string, CapturePhase[]> = {
  '準備': ['preflight', 'starting_service'],
  '錄製': ['recording'],
  '收尾': ['stopping', 'stopping_service', 'finalizing_file', 'completed', 'stopped'],
  '連線與設定': ['preflight', 'connecting', 'configuring', 'starting_service'],
  '收尾與上傳': ['stopping', 'stopping_service', 'finalizing_file', 'upload_pending', 'uploading', 'completed', 'stopped'],
};

const STEP_STATE_LABELS: Record<string, string> = {
  completed: '已完成',
  current: '進行中',
  waiting: '等待中',
  warning: '注意',
  error: '異常',
};

function stepState(step: string, child: ChildState, index: number, steps: string[]): 'completed' | 'current' | 'waiting' | 'warning' | 'error' {
  if (child.error || child.phase === 'failed' || child.file === 'failed' || child.service === 'failed') return 'error';
  if (child.service === 'presumed_running' || child.phase === 'reconciling') return 'warning';
  const phase = child.phase ?? 'idle';
  if (phase === 'unknown') return 'waiting';
  const currentIndex = steps.findIndex(item => (STEP_PHASES[item] ?? []).includes(phase));
  if (phase === 'completed' || (child.file === 'uploaded' && index === steps.length - 1)) return 'completed';
  if (phase === 'upload_pending' || phase === 'uploading') {
    if (step === '收尾與上傳') return 'current';
  }
  if (currentIndex >= 0) return index < currentIndex ? 'completed' : index === currentIndex ? 'current' : 'waiting';
  if (phase === 'idle') return 'waiting';
  return index === 0 ? 'current' : 'waiting';
}

const STEP_MARKERS = { completed: '✓', current: '●', waiting: '○', warning: '!', error: '×' };

function canStop(service: ServiceDisplay): boolean {
  return ['starting', 'running'].includes(service);
}

function canRetryStop(child: ChildState, stopRequested: boolean): boolean {
  return child.phase === 'stop_failed'
    || (stopRequested && child.phase === 'reconciling');
}

function normalizeOverall(value: unknown): DisplayState {
  return typeof value === 'string' && OVERALL_STATES.has(value as OverallState)
    ? value as OverallState
    : 'unknown';
}

const CONNECTION_STATES = new Set<ConnectionState>(['ready', 'offline', 'unknown']);
const SERVICE_STATES = new Set<ServiceState>(['idle', 'starting', 'running', 'presumed_running', 'stopping', 'stopped', 'failed']);
const FILE_STATES = new Set<FileState>(['none', 'recording', 'finalizing', 'ready', 'upload_pending', 'uploaded', 'failed']);
const CAPTURE_PHASES = new Set<CapturePhase>([
  'idle', 'preflight', 'connecting', 'configuring', 'starting_service', 'recording',
  'stopping', 'stopping_service', 'finalizing_file', 'upload_pending', 'uploading',
  'completed', 'stopped', 'reconciling', 'stop_failed', 'resume_timeout', 'failed',
]);

function normalizeChild(value: unknown): ChildState {
  const child = value && typeof value === 'object' ? value as Record<string, unknown> : {};
  const connection = typeof child.connection === 'string' && CONNECTION_STATES.has(child.connection as ConnectionState)
    ? child.connection as ConnectionState
    : 'unknown';
  const service = typeof child.service === 'string' && SERVICE_STATES.has(child.service as ServiceState)
    ? child.service as ServiceState
    : 'unknown';
  const file = typeof child.file === 'string' && FILE_STATES.has(child.file as FileState)
    ? child.file as FileState
    : 'unknown';
  const phase = child.phase === undefined
    ? 'idle'
    : typeof child.phase === 'string' && CAPTURE_PHASES.has(child.phase as CapturePhase)
      ? child.phase as CapturePhase
      : 'unknown';
  return {
    mission_id: String(child.mission_id ?? ''),
    connection,
    service,
    file,
    phase,
    error: String(child.error ?? ''),
    path: String(child.path ?? ''),
    pid: typeof child.pid === 'number' ? child.pid : null,
    last_sample_at: typeof child.last_sample_at === 'string' ? child.last_sample_at : null,
    disconnected_at: typeof child.disconnected_at === 'string' ? child.disconnected_at : null,
    resume_deadline_at: typeof child.resume_deadline_at === 'string' ? child.resume_deadline_at : null,
    upload_state: typeof child.upload_state === 'string' ? child.upload_state : 'idle',
    upload_mode: typeof child.upload_mode === 'string' ? child.upload_mode : 'none',
    upload_started_at: typeof child.upload_started_at === 'string' ? child.upload_started_at : null,
    upload_retry_mode: typeof child.upload_retry_mode === 'string' ? child.upload_retry_mode : 'none',
    upload_retry_state: typeof child.upload_retry_state === 'string' ? child.upload_retry_state : 'idle',
    upload_retry_attempt: typeof child.upload_retry_attempt === 'number' ? child.upload_retry_attempt : 0,
    upload_retry_max_attempts: typeof child.upload_retry_max_attempts === 'number' ? child.upload_retry_max_attempts : 3,
    upload_retry_next_attempt_at: typeof child.upload_retry_next_attempt_at === 'string' ? child.upload_retry_next_attempt_at : null,
    upload_retry_active_started_at: typeof child.upload_retry_active_started_at === 'string' ? child.upload_retry_active_started_at : null,
    upload_retry_last_error: typeof child.upload_retry_last_error === 'string' ? child.upload_retry_last_error : '',
    upload_job_id: typeof child.upload_job_id === 'string' ? child.upload_job_id : null,
    upload_finished_at: typeof child.upload_finished_at === 'string' ? child.upload_finished_at : null,
  };
}

function uploadProgressLabel(child: ChildState, now: number): string | null {
  if (child.upload_state !== 'running' || !child.upload_started_at) return null;
  const started = Date.parse(child.upload_started_at);
  if (Number.isNaN(started)) return null;
  const elapsed = Math.max(0, Math.floor((now - started) / 1000));
  return child.upload_mode === 'manual'
    ? `手動重試 (${elapsed} s)`
    : child.upload_retry_attempt && child.upload_retry_attempt > 0
      ? `正在重試 ${child.upload_retry_attempt}/${child.upload_retry_max_attempts ?? 3} (${elapsed} s)`
    : `上傳中 (${elapsed} s)`;
}

function uploadRetryLabel(child: ChildState, now: number): string | null {
  const attempt = child.upload_retry_attempt ?? 0;
  const maximum = child.upload_retry_max_attempts ?? 3;
  if (child.upload_retry_state === 'waiting' && child.upload_retry_next_attempt_at) {
    const next = Date.parse(child.upload_retry_next_attempt_at);
    if (!Number.isNaN(next)) {
      const remaining = Math.max(0, Math.ceil((next - now) / 1000));
      return `自動重試 ${attempt}/${maximum} (${remaining} s)`;
    }
  }
  if (child.upload_retry_state === 'exhausted') return '自動重試已用盡';
  return null;
}

function normalizeHealth(value: unknown, device: 'ap3' | 'raspi'): DeviceHealth {
  const health = value && typeof value === 'object' ? value as Record<string, unknown> : {};
  const state = typeof health.state === 'string' && CONNECTION_STATES.has(health.state as ConnectionState)
    ? health.state as ConnectionState
    : 'unknown';
  return {
    device,
    state,
    checked_at: String(health.checked_at ?? ''),
    last_checked_at: String(health.last_checked_at ?? health.checked_at ?? ''),
    next_check_at: typeof health.next_check_at === 'string' ? health.next_check_at : null,
    retry_delay: typeof health.retry_delay === 'number' ? health.retry_delay : null,
    stale: Boolean(health.stale),
    error: String(health.error ?? ''),
  };
}

export function formatTaipeiTime(value: unknown): string {
  if (typeof value !== 'string' || !value.trim()) return '—';
  const text = value.trim();
  const isNaiveIso = /^\d{4}-\d{2}-\d{2}T/.test(text)
    && !/(?:Z|[+-]\d{2}:?\d{2})$/i.test(text);
  const parsed = new Date(isNaiveIso ? `${text}+08:00` : text);
  if (Number.isNaN(parsed.getTime())) return '—';
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: 'Asia/Taipei',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hourCycle: 'h23',
  }).formatToParts(parsed).reduce<Record<string, string>>((result, part) => {
    result[part.type] = part.value;
    return result;
  }, {});
  if (!parts.month || !parts.day || !parts.hour || !parts.minute || !parts.second) return '—';
  return `${parts.month}/${parts.day} ${parts.hour}:${parts.minute}:${parts.second}`;
}

function normalizeSummary(value: unknown): MissionSummary | null {
  if (!value || typeof value !== 'object') return null;
  const summary = value as Record<string, unknown>;
  const startedAt = typeof summary.started_at === 'string' ? summary.started_at : '';
  const missionId = typeof summary.mission_id === 'string' ? summary.mission_id : '';
  if (!startedAt || !missionId) return null;
  return { started_at: startedAt, mission_id: missionId };
}

function missionSummaryLabel(summary: MissionSummary | null | undefined): string {
  if (!summary?.mission_id || !summary.started_at) return '—';
  return `${formatTaipeiTime(summary.started_at)} #${summary.mission_id.slice(-5)}`;
}

function childIssue(name: 'GPS' | 'Noise', child: ChildState): string | null {
  if (child.phase === 'resume_timeout') return `${name} 恢復逾時`;
  if (child.service === 'failed' || child.file === 'failed') return `${name} 失敗`;
  if (child.connection === 'offline') return `${name} 離線`;
  if (child.service === 'presumed_running' || child.phase === 'reconciling') {
    return `${name} 狀態不確定`;
  }
  return null;
}

function missionLabel(status: CaptureStatus | null): string {
  if (!status) return OVERALL_LABELS.unknown;
  return OVERALL_LABELS[status.overall_state];
}

function normalizeStatus(value: Partial<CaptureStatus>): CaptureStatus {
  const activeValue = value.active && typeof value.active === 'object'
    ? value.active
    : null;
  const hasProjection = 'active' in value || 'control_mode' in value;
  const cleanChild = (child: unknown) => {
    const raw = child && typeof child === 'object' ? child as Record<string, unknown> : {};
    return {
      ...raw,
      mission_id: '',
      service: 'idle',
      file: 'none',
      phase: 'idle',
      error: '',
      path: '',
      pid: null,
      upload_state: 'idle',
      upload_mode: 'none',
      upload_retry_mode: 'none',
      upload_retry_state: 'idle',
    };
  };
  // An active projection is authoritative.  This also lets a frontend
  // consume a status response that carries terminal compatibility fields at
  // the top level without rehydrating those fields into the panel.
  const source = activeValue
    ? { ...value, ...activeValue, device_health: value.device_health, history: value.history }
    : hasProjection
      ? {
        ...value,
        mission_id: '',
        target: 'bind' as const,
        bind: false,
        overall_state: 'ready' as const,
        started_at: null,
        finished_at: null,
        stop_requested_at: null,
        uav: cleanChild(value.uav),
        usrp: cleanChild(value.usrp),
      }
    : value;
  const history = source.history && typeof source.history === 'object'
    ? {
      gps: normalizeSummary(source.history.gps),
      noise: normalizeSummary(source.history.noise),
    }
    : undefined;
  return {
    mission_id: String(source.mission_id ?? ''),
    target: source.target === 'usrp' || source.target === 'bind' ? source.target : 'uav',
    bind: Boolean(source.bind),
    selected_usrp_mode: source.selected_usrp_mode === 'usrp' ? 'usrp' : 'test',
    overall_state: normalizeOverall(source.overall_state),
    created_at: String(source.created_at ?? ''),
    started_at: source.started_at ?? null,
    finished_at: source.finished_at ?? null,
    stop_requested_at: source.stop_requested_at ?? null,
    uav: normalizeChild(source.uav),
    usrp: normalizeChild(source.usrp),
    device_health: source.device_health && typeof source.device_health === 'object'
      ? {
        ap3: normalizeHealth(source.device_health.ap3, 'ap3'),
        raspi: normalizeHealth(source.device_health.raspi, 'raspi'),
      }
      : undefined,
    control_mode: value.control_mode === 'bound' ? 'bound' : 'independent',
    active: value.active ?? null,
    history,
  };
}

function responseMessage(value: unknown, fallback: string): string {
  if (value && typeof value === 'object') {
    const body = value as CaptureErrorBody;
    const detail = body.detail;
    if (typeof detail === 'string') return detail;
    const source: CapturePreflightErrorBody = detail && typeof detail === 'object'
      ? detail
      : { errors: body.errors ?? body.preflight_errors };
    const labels: Record<string, string> = { ap3: 'AP3', raspi: 'Raspberry Pi' };
    const formatMap = (values: DeviceErrorMap | undefined): string | null => {
      if (!values) return null;
      const entries = Object.entries(values)
        .filter(([, message]) => typeof message === 'string' && message.trim())
        .map(([device, message]) => `${labels[device] ?? device}: ${message}`);
      return entries.length ? entries.join('; ') : null;
    };
    const direct = detail && typeof detail === 'object'
      ? detail as CapturePreflightErrorBody & Record<string, unknown>
      : null;
    const directErrors = direct && (direct.ap3 !== undefined || direct.raspi !== undefined)
      ? { ap3: String(direct.ap3 ?? ''), raspi: String(direct.raspi ?? '') }
      : undefined;
    const mapped = formatMap(source.errors ?? source.preflight_errors ?? directErrors);
    if (mapped) return mapped;
    const devices = source.devices;
    if (devices && !Array.isArray(devices)) {
      const mappedDevices = formatMap(devices);
      if (mappedDevices) return mappedDevices;
    }
    if (Array.isArray(devices)) {
      const entries = devices
        .filter(item => item && typeof item === 'object')
        .filter((item): item is CaptureDeviceError => Boolean(item && typeof item === 'object'))
        .filter(item => typeof item.error === 'string' && item.error.trim())
        .map(item => `${labels[String(item.device)] ?? String(item.device ?? 'Device')}: ${item.error}`);
      if (entries.length) return entries.join('; ');
    }
    if (typeof source.message === 'string') return source.message;
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

function splitRequestError(path: string, message: string): { gps?: string; noise?: string; common?: string } {
  if (path.includes('/uav/')) return { gps: message };
  if (path.includes('/usrp/')) return { noise: message };
  if (!path.includes('/bind/')) return { common: message };
  const entries = message.split(';').map(item => item.trim()).filter(Boolean);
  const gps = entries.filter(item => item.startsWith('AP3:')).join('; ');
  const noise = entries.filter(item => item.startsWith('Raspberry Pi:')).join('; ');
  const common = entries.filter(item => !item.startsWith('AP3:') && !item.startsWith('Raspberry Pi:')).join('; ');
  return {
    ...(gps ? { gps } : {}),
    ...(noise ? { noise } : {}),
    ...(common ? { common } : {}),
  };
}

interface USRPTelemetryProps {
  sceneId?: string | null;
}

export function USRPTelemetry({ sceneId = 'NTPU' }: USRPTelemetryProps) {
  const [mode, setMode] = useState<SamplingMode>('test');
  const [bind, setBind] = useState(false);
  const [status, setStatus] = useState<CaptureStatus | null>(null);
  const [health, setHealth] = useState<Record<string, DeviceHealth>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [gpsError, setGpsError] = useState('');
  const [noiseError, setNoiseError] = useState('');
  const [now, setNow] = useState(() => Date.now());
  const id = useId();
  const statusFlight = useRef<Promise<boolean> | null>(null);
  const statusController = useRef<AbortController | null>(null);
  const mounted = useRef(false);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      statusController.current?.abort();
    };
  }, []);

  const applyStatus = useCallback((data: Partial<CaptureStatus>) => {
    const next = normalizeStatus(data);
    setStatus(next);
    setGpsError('');
    setNoiseError('');
    if (next.device_health) setHealth(next.device_health);
    if ('active' in data || 'control_mode' in data) {
      if (next.active) {
        setBind(next.control_mode === 'bound' || next.bind);
      } else {
        // The backend deliberately returns Independent for an idle
        // projection; terminal history must never rehydrate Bound mode.
        setBind(false);
      }
    } else if (next.bind && (isUnresolved(next.uav) || isUnresolved(next.usrp))) {
      setBind(true);
    }
    if (isActive(next.usrp.service) || isUnresolved(next.usrp)) {
      setMode(next.selected_usrp_mode);
    }
  }, []);

  const loadHealth = useCallback(async () => {
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 8000);
    try {
      const response = await fetch(`${API}/api/capture/health?usrp_mode=${mode}`, { signal: controller.signal });
      const data = await readCaptureResponse(response, '裝置健康檢查失敗') as Partial<{ device_health: Record<string, unknown> }>;
      const values = data.device_health;
      if (values && typeof values === 'object') {
        setHealth({
          ap3: normalizeHealth(values.ap3, 'ap3'),
          raspi: normalizeHealth(values.raspi, 'raspi'),
        });
      }
    } catch (requestError) {
      setHealth((previous) => Object.fromEntries(
        (['ap3', 'raspi'] as const).map((device) => [device, {
          ...(previous[device] ?? normalizeHealth({}, device)),
          state: 'unknown',
          stale: true,
          error: requestError instanceof Error && requestError.name === 'AbortError'
            ? `${device} health probe timed out`
            : requestError instanceof Error ? requestError.message : '裝置健康檢查失敗',
        }]),
      ));
      if (requestError instanceof Error && requestError.name !== 'AbortError') setError(requestError.message);
    } finally {
      window.clearTimeout(timeout);
    }
  }, [mode]);

  const loadStatus = useCallback(() => {
    if (statusFlight.current) return statusFlight.current;
    const controller = new AbortController();
    statusController.current = controller;
    const timeout = window.setTimeout(() => controller.abort(), 25000);
    let flight!: Promise<boolean>;
    flight = (async () => {
      try {
        const response = await fetch(`${API}/api/capture/status?usrp_mode=${mode}`, { signal: controller.signal });
        const data = await readCaptureResponse(response, '狀態讀取失敗');
        if (!mounted.current) return false;
        applyStatus(data);
        setError('');
        return true;
      } catch (requestError) {
        if (mounted.current) {
          setError(requestError instanceof Error && requestError.name === 'AbortError' ? '狀態讀取逾時' : requestError instanceof Error ? requestError.message : '狀態讀取失敗');
        }
        return false;
      } finally {
        window.clearTimeout(timeout);
        if (statusController.current === controller) statusController.current = null;
        if (statusFlight.current === flight) statusFlight.current = null;
      }
    })();
    statusFlight.current = flight;
    return flight;
  }, [applyStatus, mode]);

  const refreshStatus = useCallback(async () => {
    const pending = statusFlight.current;
    if (pending) await pending;
    if (!mounted.current) return false;
    return loadStatus();
  }, [loadStatus]);

  useEffect(() => {
    void loadStatus();
  }, [loadStatus]);

  const uploadRunning = status?.usrp.upload_state === 'running';
  const uploadWaiting = status?.usrp.upload_retry_state === 'waiting';
  useEffect(() => {
    if (!uploadRunning && !uploadWaiting) return;
    setNow(Date.now());
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [uploadRunning, uploadWaiting]);

  useEffect(() => {
    let active = true;
    let timer: number | undefined;
    const poll = async () => {
      if (!active) return;
      await loadHealth();
      if (active) timer = window.setTimeout(poll, 10000);
    };
    void poll();
    return () => {
      active = false;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [loadHealth]);

  const shouldPoll = Boolean(
    status && (
      isPollingPhase(status.uav.phase) ||
      isActive(status.uav.service) ||
      isPollingPhase(status.usrp.phase) ||
      isActive(status.usrp.service) ||
      ['finalizing', 'upload_pending'].includes(status.uav.file) ||
      ['finalizing', 'upload_pending'].includes(status.usrp.file)
    )
  );

  useEffect(() => {
    if (!shouldPoll) return;
    let active = true;
    let timer: number | undefined;
    const schedule = () => {
      if (!active) return;
      timer = window.setTimeout(async () => {
        if (!active) return;
        await loadStatus();
        schedule();
      }, 2000);
    };
    schedule();
    return () => {
      active = false;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [loadStatus, shouldPoll]);

  const request = useCallback(async (path: string, body?: object) => {
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 35000);
    setBusy(true);
    setError('');
    setGpsError('');
    setNoiseError('');
    try {
      const response = await fetch(`${API}${path}`, {
        method: 'POST', signal: controller.signal,
        ...(body
          ? { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }
          : {}),
      });
      const data = await readCaptureResponse(response, '採樣操作失敗');
      const synced = await refreshStatus();
      if (!synced && mounted.current) applyStatus(data);
    } catch (requestError) {
      const message = requestError instanceof Error && requestError.name === 'AbortError'
        ? '採樣操作逾時，正在同步任務狀態。'
        : requestError instanceof Error ? requestError.message : '採樣操作失敗';
      const scoped = splitRequestError(path, message);
      if (scoped.gps) setGpsError(scoped.gps);
      if (scoped.noise) setNoiseError(scoped.noise);
      if (scoped.common) setError(scoped.common);
    } finally {
      window.clearTimeout(timeout);
      setBusy(false);
    }
  }, [applyStatus, refreshStatus]);

  const startBody = useMemo(
    () => ({ usrp_mode: mode, scene: sceneId ?? 'NTPU', map_type: 'iss' }),
    [mode, sceneId],
  );
  const uav = status?.uav ?? EMPTY_CHILD;
  const usrp = status?.usrp ?? EMPTY_CHILD;
  const missionId = status?.mission_id ?? '';
  const uavMissionId = uav.mission_id || missionId;
  const usrpMissionId = usrp.mission_id || missionId;
  const ap3Health = health.ap3;
  const raspiHealth = health.raspi;
  const gpsHistory = status?.history?.gps;
  const noiseHistory = status?.history?.noise;
  const ap3Ready = ap3Health?.state === 'ready' && !ap3Health.stale;
  const raspiReady = raspiHealth?.state === 'ready' && !raspiHealth.stale;
  const anyActive = isActive(uav.service) || isActive(usrp.service);
  const overallLabel = missionLabel(status);
  const overallTone = status?.overall_state === 'failed'
    ? 'danger'
    : status?.overall_state === 'degraded'
      || status?.overall_state === 'stopping'
      || status?.overall_state === 'finalizing'
      || status?.overall_state === 'completed_with_warning'
      ? 'warning'
      : status?.overall_state === 'ready'
        || status?.overall_state === 'starting'
        || status?.overall_state === 'running'
        || status?.overall_state === 'completed'
          ? 'live'
          : anyActive ? 'live' : 'waiting';
  const uavKnown = uav.connection !== 'unknown' && uav.service !== 'unknown'
    && uav.file !== 'unknown' && uav.phase !== 'unknown';
  const usrpKnown = usrp.connection !== 'unknown' && usrp.service !== 'unknown'
    && usrp.file !== 'unknown' && usrp.phase !== 'unknown';
  const controlsLocked = busy || isUnresolved(uav) || isUnresolved(usrp);
  const noiseModeLocked = busy || isUnresolved(usrp) || !raspiReady;
  const bothReady = uavKnown && usrpKnown && ap3Ready && raspiReady;
  const canStartUav = uavKnown && !bind && !busy && !isUnresolved(uav) && ap3Ready;
  // Control Mode is only a projection switch; an unresolved child must be
  // able to announce its blocker even when the sibling health projection is
  // unknown.  Before the first status response there is no mode to switch.
  const modeDisabled = busy || status === null;
  const modeReason = modeDisabled
    ? busy ? '操作進行中，請稍候。' : '正在讀取任務狀態。'
    : null;
  const disabledStyle = (disabled: boolean) => ({ opacity: disabled ? 0.45 : 1 });
  const uavStartReason = !canStartUav
    ? !ap3Ready
      ? 'AP3 尚未就緒。'
      : bind
        ? '綁定任務模式請使用「開始綁定任務」。'
        : busy
          ? '操作進行中，請稍候。'
          : !uavKnown
            ? 'GPS 任務狀態尚未就緒。'
            : isUnresolved(uav)
              ? '請先完成目前 GPS 任務。'
              : null
    : null;
  const noiseModeReason = noiseModeLocked || !usrpKnown
    ? busy
      ? '操作進行中，請稍候。'
      : !usrpKnown
        ? 'Noise 任務狀態尚未就緒。'
        : isUnresolved(usrp)
          ? '請先完成目前 Noise 任務。'
          : 'Raspberry Pi 尚未就緒。'
    : null;
  const noiseModeDisabled = noiseModeLocked || !usrpKnown;
  const noiseStartDisabled = bind || busy || !usrpKnown || isUnresolved(usrp) || !raspiReady;
  const noiseStartReason = noiseStartDisabled
    ? bind
      ? '綁定任務模式請使用「開始綁定任務」。'
      : !raspiReady
        ? 'Raspberry Pi 尚未就緒。'
        : busy
          ? '操作進行中，請稍候。'
          : !usrpKnown
            ? 'Noise 任務狀態尚未就緒。'
            : '請先完成目前 Noise 任務。'
    : null;
  const boundStartDisabled = controlsLocked || !bothReady;
  const boundStartReason = boundStartDisabled
    ? busy
      ? '操作進行中，請稍候。'
      : controlsLocked
        ? '請先完成目前 GPS 與 Noise 任務。'
        : '請確認 GPS、Noise 與裝置都已就緒。'
    : null;
  const uncertainBound = [uav, usrp].some(child => (
    child.service === 'presumed_running' || child.phase === 'reconciling'
  ));
  const boundStopDisabled = busy || !missionId || !anyActive || uncertainBound || Boolean(status?.stop_requested_at);
  const boundStopReason = boundStopDisabled
    ? busy
      ? '操作進行中，請稍候。'
      : Boolean(status?.stop_requested_at)
        ? '已送出停止要求，正在處理。'
        : uncertainBound
          ? '任務狀態不確定，請先同步狀態。'
        : !missionId
          ? '目前沒有綁定任務。'
        : '目前沒有可停止的綁定任務。'
    : null;
  const boundIdle = bind && !anyActive && !isUnresolved(uav) && !isUnresolved(usrp);
  const gpsIssue = childIssue('GPS', uav);
  const noiseIssue = childIssue('Noise', usrp);
  const switchMode = () => {
    const notice = modeBlocker(bind, status);
    if (notice) {
      setError(notice);
      return;
    }
    setError('');
    setBind(value => !value);
  };
  const stopAction = (
    target: 'uav' | 'usrp',
    child: ChildState,
    childMissionId: string,
  ) => {
    const retry = canRetryStop(child, Boolean(status?.stop_requested_at));
    const stopped = child.service === 'stopped';
    const raspiUnavailable = target === 'usrp' && !raspiReady;
    const disabled = busy || stopped || (retry ? raspiUnavailable : !canStop(child.service));
    const name = target === 'uav' ? 'GPS 採樣' : 'Noise 採樣';
    const label = stopped ? `${name}已停止` : retry ? `重試停止 ${name}` : `停止 ${name}`;
    const text = stopped ? `已停止 ${name}` : retry ? `重試停止 ${name}` : `停止 ${name}`;
    const reason = disabled
      ? busy
        ? '操作進行中，請稍候。'
        : retry && raspiUnavailable
          ? '請先重新連線 Raspberry Pi，再重試停止。'
            : stopped
              ? `${name}已停止。`
              : child.service === 'presumed_running' || child.phase === 'reconciling'
                ? `${name}狀態不確定，請先同步狀態。`
              : child.service === 'unknown'
                ? `${name}狀態未知。`
              : `目前沒有可停止的${name}。`
      : null;
    const reasonId = `${id}-${target}-stop`;
    const path = retry
      ? `/api/capture/${target}/retry-stop?mission_id=${encodeURIComponent(childMissionId)}`
      : `/api/capture/${target}/stop?mission_id=${encodeURIComponent(childMissionId)}`;
    return <>
      <button
        type="button"
        style={{ ...S.button, ...S.primary, ...S.stop, ...disabledStyle(disabled) }}
        disabled={disabled}
        aria-label={label}
        aria-describedby={reason ? reasonId : undefined}
        title={reason ?? undefined}
        onClick={() => void request(path)}
      >
        {text}
      </button>
      {reason ? <div id={reasonId} role="status" style={S.blocker}>{reason}</div> : null}
    </>;
  };

  const childSection = (
    kind: 'gps' | 'noise',
    title: string,
    summary: MissionSummary | null | undefined,
    child: ChildState,
    childError: string,
    actions: React.ReactNode,
    steps: string[],
  ) => {
    const retryLabel = uploadRetryLabel(child, now);
    const progressLabel = uploadProgressLabel(child, now);
    const name = kind === 'noise' ? 'Noise' : 'GPS';
    const issue = childIssue(name, child);
    const autoRetryActive = child.upload_retry_mode === 'automatic'
      && ['waiting', 'running'].includes(child.upload_retry_state ?? '');
    return <section style={S.section}>
      <div style={S.sectionTitle}>{title}</div>
      <div style={S.rows}>
        <span style={S.key}>連線</span>
        <span style={S.value}>{CONNECTION_LABELS[child.connection]}</span>
        <span style={S.key}>階段</span>
        <span style={S.value} aria-live="polite">{PHASE_LABELS[child.phase ?? 'unknown']}</span>
        <span style={S.key}>服務</span>
        <span style={S.value}>{SERVICE_LABELS[child.service]}</span>
        <span style={S.key}>檔案</span>
        <span style={S.value}>{FILE_LABELS[child.file]}</span>
      </div>
      <details style={{ marginTop: 8 }}>
        <summary style={{ cursor: 'pointer', color: 'rgba(210, 230, 255, 0.72)', fontSize: 11 }}>
          歷史任務與詳細進度
        </summary>
        <div style={{ ...S.rows, marginTop: 6 }}>
          <span style={S.key}>上次任務</span>
          <span style={S.value} aria-label={`${title} 上次任務`}>{missionSummaryLabel(summary)}</span>
          {child.last_sample_at ? <>
            <span style={S.key}>最後 {name}</span>
            <span style={S.value}>{formatTaipeiTime(child.last_sample_at)}</span>
          </> : null}
        </div>
        <div style={S.steps} aria-label={`${title} 進度`}>
          {steps.map((step, index) => {
            const state = stepState(step, child, index, steps);
            return <div key={step} data-step-state={state}>{STEP_MARKERS[state]} {step} — {STEP_STATE_LABELS[state] ?? state}</div>;
          })}
        </div>
      </details>
      {issue ? <div role="status" style={S.blocker}>{issue}</div> : null}
      {childError ? <div role="alert" style={S.error}>{childError}</div> : null}
      {child.error ? <div role="alert" style={S.error}>{child.error}</div> : null}
      {child.phase === 'resume_timeout' && child.file === 'ready' ? (
        <div style={S.error}>可用的部分 GPS 檔案。</div>
      ) : null}
      {child.service === 'presumed_running' ? <div style={S.error}>目前推定仍在執行，請先同步狀態再停止。</div> : null}
      {child.service === 'stopped' && child.file === 'upload_pending' ? <div style={S.error}>已停止；等待上傳。</div> : null}
      {retryLabel ? <div aria-live="polite" style={S.error}>{retryLabel}</div> : null}
      {progressLabel ? <div aria-live="polite" style={S.error}>{progressLabel}</div> : null}
      {kind === 'noise' && !bind && child.file === 'upload_pending' && !autoRetryActive ? <button type="button" style={S.button} aria-label="重試上傳" disabled={busy || child.upload_state === 'running'} onClick={() => void request(`/api/capture/usrp/upload/retry?mission_id=${encodeURIComponent(child.mission_id || missionId)}`)}>重試上傳</button> : null}
      {actions}
    </section>
  };

  const noiseModePicker = <>
    <div style={S.modes} aria-label="Noise 採樣模式">
      {(['test', 'usrp'] as SamplingMode[]).map(value => (
        <button
          key={value}
          type="button"
          aria-label={value === 'test' ? '測試模式' : 'USRP 模式'}
          aria-pressed={mode === value}
          disabled={noiseModeDisabled}
          aria-describedby={noiseModeReason ? `${id}-noise-mode` : undefined}
          style={{
            ...S.button,
            ...(mode === value ? S.active : null),
            ...disabledStyle(noiseModeDisabled),
          }}
          onClick={() => setMode(value)}
        >
          {value === 'test' ? '測試' : 'USRP'}
        </button>
      ))}
    </div>
    {noiseModeReason ? <div id={`${id}-noise-mode`} role="status" style={S.blocker}>{noiseModeReason}</div> : null}
  </>;

  const noiseControls = () => {
    if (bind) {
      if (boundIdle) return noiseModePicker;
      return canRetryStop(usrp, Boolean(status?.stop_requested_at))
        ? <div style={S.actions}>{stopAction('usrp', usrp, usrpMissionId)}</div>
        : null;
    }
    return <>
      {noiseModePicker}
      <div style={S.actions}>
        <>
          <button
            type="button"
            style={{ ...S.button, ...S.primary, ...disabledStyle(noiseStartDisabled) }}
            disabled={noiseStartDisabled}
            aria-label="開始 Noise 採樣"
            aria-describedby={noiseStartReason ? `${id}-noise-start` : undefined}
            onClick={() => void request('/api/capture/usrp/start', startBody)}
          >
            開始 Noise 採樣
          </button>
          {noiseStartReason ? <div id={`${id}-noise-start`} role="status" style={S.blocker}>{noiseStartReason}</div> : null}
          {stopAction('usrp', usrp, usrpMissionId)}
        </>
      </div>
    </>;
  };

  return (
    <MinPanel
      title="採樣控制面板"
      className="panel-ui"
      toggleLabel={(isMinimized) => `${isMinimized ? '展開' : '收合'} 採樣控制面板`}
      actions={<PanelStatus tone={overallTone} label={overallLabel} />}
    >
      <div style={S.control}>
        <div style={S.topRow}>
          <div
            style={{ ...S.modes, flex: 1 }}
            role="group"
            aria-label="控制模式"
            aria-describedby={modeReason ? `${id}-mode-blocker` : undefined}
          >
            <button
              type="button"
              aria-label="獨立採樣模式"
              aria-pressed={!bind}
              disabled={modeDisabled}
              style={{
                ...S.button,
                ...(!bind ? S.active : null),
                ...disabledStyle(modeDisabled),
                flex: 1,
              }}
              onClick={() => {
                if (bind) switchMode();
              }}
            >
              獨立採樣模式
            </button>
            <button
              type="button"
              aria-label="綁定任務模式"
              aria-pressed={bind}
              disabled={modeDisabled}
              style={{
                ...S.button,
                ...(bind ? S.active : null),
                ...disabledStyle(modeDisabled),
                flex: 1,
              }}
              onClick={switchMode}
            >
              綁定任務模式
            </button>
          </div>
          <button
            type="button"
            style={S.button}
            aria-label="重新整理狀態"
            disabled={busy}
            aria-describedby={busy ? `${id}-mode-blocker` : undefined}
            onClick={() => void loadStatus()}
          >
            重新整理狀態
          </button>
        </div>
        {modeReason ? <div id={`${id}-mode-blocker`} role="status" style={S.blocker}>{modeReason}</div> : null}

        <div style={S.sectionTitle}>裝置就緒</div>
        <div style={S.health} aria-label="裝置就緒">
          {(['ap3', 'raspi'] as const).map((device) => {
            const item = health[device];
            const label = device === 'ap3' ? 'AP3' : 'Raspberry Pi';
            const state = item?.stale ? 'unknown' : item?.state ?? 'unknown';
            return (
              <div key={device} style={S.healthCard} aria-label={`${label} 裝置就緒`}>
                <strong>{label}</strong>
                <div style={S.value}>{CONNECTION_LABELS[state]}</div>
                {item?.last_checked_at ? <div>最後檢查：{formatTaipeiTime(item.last_checked_at)}</div> : null}
                {item?.error ? <div style={S.error}>{item.error}</div> : null}
              </div>
            );
          })}
        </div>

        <div style={S.sectionTitle}>任務狀態</div>

        {childSection(
          'gps',
          '無人機 GPS 採樣',
          gpsHistory,
          uav,
          gpsError,
          <div style={S.actions}>
            {!bind ? <>
              <button
                type="button"
                style={{ ...S.button, ...S.primary, ...disabledStyle(!canStartUav) }}
                disabled={!canStartUav}
                aria-label="開始 GPS 採樣"
                aria-describedby={uavStartReason ? `${id}-uav-start` : undefined}
                onClick={() => void request('/api/capture/uav/start')}
              >
                開始 GPS 採樣
              </button>
              {uavStartReason ? <div id={`${id}-uav-start`} role="status" style={S.blocker}>{uavStartReason}</div> : null}
            </> : null}
            {!bind && uav.phase === 'resume_timeout' ? (
              <button
                type="button"
                style={{ ...S.button, ...S.primary }}
                aria-label="恢復 GPS 採樣"
                onClick={() => void request(`/api/capture/uav/resume?mission_id=${encodeURIComponent(uavMissionId)}`)}
              >
                恢復 GPS 採樣
              </button>
            ) : null}
            {!bind || canRetryStop(uav, Boolean(status?.stop_requested_at))
              ? stopAction('uav', uav, uavMissionId)
              : null}
          </div>,
          ['準備', '錄製', '收尾'],
        )}

        {childSection(
          'noise',
          'Noise 採樣',
          noiseHistory,
          usrp,
          noiseError,
          noiseControls(),
          ['連線與設定', '錄製', '收尾與上傳'],
        )}

        {bind ? (
          <div style={S.actions}>
            <button
              type="button"
              style={{ ...S.button, ...S.primary, ...S.active, ...disabledStyle(boundStartDisabled) }}
              disabled={boundStartDisabled}
              aria-label="開始綁定任務"
              aria-describedby={boundStartReason ? `${id}-bound-start` : undefined}
              onClick={() => void request('/api/capture/bind/start', startBody)}
            >
              開始綁定任務
            </button>
            {boundStartReason ? <div id={`${id}-bound-start`} role="status" style={S.blocker}>{boundStartReason}</div> : null}
            <button
              type="button"
              style={{ ...S.button, ...S.primary, ...S.stop, ...disabledStyle(boundStopDisabled) }}
              disabled={boundStopDisabled}
              aria-label="停止綁定任務"
              aria-describedby={boundStopReason ? `${id}-bound-stop` : undefined}
              onClick={() => void request(`/api/capture/bind/stop?mission_id=${encodeURIComponent(missionId)}`)}
            >
              停止綁定任務
            </button>
            {boundStopReason ? <div id={`${id}-bound-stop`} role="status" style={S.blocker}>{boundStopReason}</div> : null}
          </div>
        ) : null}

        {missionId ? <div style={S.mission}>任務：{missionId}</div> : null}
        {error ? <div role="alert" style={S.error}>{error}</div> : null}
      </div>

    </MinPanel>
  );
}
