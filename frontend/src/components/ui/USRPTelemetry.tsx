import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
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
  idle: 'Idle', preflight: 'Preflight', connecting: 'Connecting', configuring: 'Configuring',
  starting_service: 'Starting service', recording: 'Recording', stopping_service: 'Stopping service',
  finalizing_file: 'Finalizing CSV', upload_pending: 'Upload pending', uploading: 'Uploading',
  stopping: 'Stopping', completed: 'Complete', stopped: 'Stopped',
  reconciling: 'Reconciling presumed-running state', stop_failed: 'Stop failed',
  resume_timeout: 'Resume timeout', failed: 'Failed', unknown: 'Unknown',
};

const CONNECTION_LABELS: Record<ConnectionState, string> = {
  ready: 'Ready',
  offline: 'Offline',
  unknown: 'Unknown',
};

const SERVICE_LABELS: Record<ServiceDisplay, string> = {
  idle: 'Idle',
  starting: 'Starting',
  running: 'Running',
  presumed_running: 'Presumed running',
  stopping: 'Stopping',
  stopped: 'Stopped',
  failed: 'Failed',
  unknown: 'Unknown',
};

const FILE_LABELS: Record<FileDisplay, string> = {
  none: 'None',
  recording: 'Recording',
  finalizing: 'Finalizing',
  ready: 'Ready',
  upload_pending: 'Pending upload',
  uploaded: 'Uploaded',
  failed: 'Failed',
  unknown: 'Unknown',
};

const OVERALL_STATES = new Set<OverallState>([
  'ready', 'starting', 'running', 'degraded', 'stopping', 'finalizing',
  'completed', 'completed_with_warning', 'failed',
]);

const OVERALL_LABELS: Record<DisplayState, string> = {
  ready: 'READY', starting: 'STARTING', running: 'RUNNING', degraded: 'DEGRADED',
  stopping: 'STOPPING', finalizing: 'FINALIZING', completed: 'COMPLETED',
  completed_with_warning: 'COMPLETED WITH WARNING', failed: 'FAILED', unknown: 'UNKNOWN',
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
    || ['stopping', 'stopping_service', 'finalizing_file', 'upload_pending', 'uploading', 'reconciling', 'stop_failed'].includes(child.phase ?? 'idle');
}

function isPollingPhase(phase?: PhaseDisplay): boolean {
  return Boolean(phase && [
    'preflight', 'connecting', 'configuring', 'starting_service', 'recording',
    'stopping', 'stopping_service', 'finalizing_file', 'upload_pending',
    'uploading', 'reconciling', 'stop_failed',
  ].includes(phase));
}

const STEP_PHASES: Record<string, CapturePhase[]> = {
  'Start recorder': ['starting_service'],
  'Record': ['recording'],
  'Stop recorder': ['stopping_service'],
  'Finalize CSV': ['finalizing_file'],
  'Connect': ['connecting'],
  'Configure': ['configuring', 'preflight'],
  'Start service': ['starting_service'],
  'Stop service': ['stopping_service'],
  'Upload': ['upload_pending', 'uploading'],
  'Complete': ['completed'],
};

function stepState(step: string, child: ChildState, index: number, steps: string[]): 'completed' | 'current' | 'waiting' | 'warning' | 'error' {
  if (child.error || child.phase === 'failed' || child.file === 'failed' || child.service === 'failed') return 'error';
  if (child.service === 'presumed_running' || child.phase === 'reconciling') return 'warning';
  const phase = child.phase ?? 'idle';
  if (phase === 'unknown') return 'waiting';
  const currentIndex = steps.findIndex(item => (STEP_PHASES[item] ?? []).includes(phase));
  if (phase === 'completed' || (child.file === 'uploaded' && index === steps.length - 1)) return 'completed';
  if (phase === 'upload_pending' || phase === 'uploading') {
    if (step === 'Upload') return 'current';
    if (step === 'Complete') return 'waiting';
  }
  if (currentIndex >= 0) return index < currentIndex ? 'completed' : index === currentIndex ? 'current' : 'waiting';
  if (phase === 'idle') return 'waiting';
  return index === 0 ? 'current' : 'waiting';
}

const STEP_MARKERS = { completed: '✓', current: '●', waiting: '○', warning: '!', error: '×' };

function canStop(service: ServiceDisplay): boolean {
  return ['starting', 'running', 'presumed_running'].includes(service);
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
  };
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

function missionIssue(status: CaptureStatus, failuresOnly = false): string | null {
  const children = [['GPS', status.uav], ['NOISE', status.usrp]] as const;
  const resumeTimeout = children
    .find(([, child]) => child.phase === 'resume_timeout');
  if (resumeTimeout) return `${resumeTimeout[0]} RESUME TIMEOUT`;
  const failed = children
    .find(([, child]) => child.service === 'failed' || child.file === 'failed');
  if (failed) return `${failed[0]} FAILED`;
  if (failuresOnly) return null;
  const offline = children.find(([, child]) => child.connection === 'offline');
  if (offline) return `${offline[0]} OFFLINE`;
  const uncertain = children.find(([, child]) => (
    child.service === 'presumed_running' || child.phase === 'reconciling'
  ));
  return uncertain ? `${uncertain[0]} UNCERTAIN` : null;
}

function childAction(name: 'GPS' | 'NOISE', child: ChildState): string | null {
  if (
    child.connection !== 'ready'
    || child.service === 'failed'
    || child.service === 'presumed_running'
    || child.file === 'failed'
  ) return null;
  if (child.file === 'recording') return `${name} RECORDING`;
  if (child.service === 'starting') return `${name} STARTING`;
  if (child.service === 'stopping') return `${name} STOPPING`;
  if (child.file === 'finalizing' || child.file === 'upload_pending') return `${name} FINALIZING`;
  return null;
}

function missionLabel(status: CaptureStatus | null): string {
  if (!status) return 'UNKNOWN';
  const label = OVERALL_LABELS[status.overall_state];
  if (status.overall_state === 'degraded') {
    const issue = missionIssue(status);
    const action = issue?.startsWith('GPS ')
      ? childAction('NOISE', status.usrp)
      : childAction('GPS', status.uav);
    return [label, issue, action].filter(Boolean).join(' · ');
  }
  if (status.overall_state === 'completed_with_warning') {
    return [label, missionIssue(status, true)]
      .filter(Boolean)
      .join(' · ');
  }
  return label;
}

function normalizeStatus(value: Partial<CaptureStatus>): CaptureStatus {
  return {
    mission_id: String(value.mission_id ?? ''),
    target: value.target === 'usrp' || value.target === 'bind' ? value.target : 'uav',
    bind: Boolean(value.bind),
    selected_usrp_mode: value.selected_usrp_mode === 'usrp' ? 'usrp' : 'test',
    overall_state: normalizeOverall(value.overall_state),
    created_at: String(value.created_at ?? ''),
    started_at: value.started_at ?? null,
    finished_at: value.finished_at ?? null,
    stop_requested_at: value.stop_requested_at ?? null,
    uav: normalizeChild(value.uav),
    usrp: normalizeChild(value.usrp),
    device_health: value.device_health && typeof value.device_health === 'object'
      ? {
        ap3: normalizeHealth(value.device_health.ap3, 'ap3'),
        raspi: normalizeHealth(value.device_health.raspi, 'raspi'),
      }
      : undefined,
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
  const statusFlight = useRef<Promise<void> | null>(null);
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
    if (next.device_health) setHealth(next.device_health);
    if (next.bind && (isUnresolved(next.uav) || isUnresolved(next.usrp))) {
      setBind(true);
    }
    if (isActive(next.usrp.service)) {
      setMode(next.selected_usrp_mode);
    }
  }, []);

  const loadHealth = useCallback(async () => {
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 8000);
    try {
      const response = await fetch(`${API}/api/capture/health?usrp_mode=${mode}`, { signal: controller.signal });
      const data = await readCaptureResponse(response, 'Device Health request failed') as Partial<{ device_health: Record<string, unknown> }>;
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
            : requestError instanceof Error ? requestError.message : 'Device Health request failed',
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
    let flight!: Promise<void>;
    flight = (async () => {
      try {
        const response = await fetch(`${API}/api/capture/status?usrp_mode=${mode}`, { signal: controller.signal });
        const data = await readCaptureResponse(response, 'Status request failed');
        if (!mounted.current) return;
        applyStatus(data);
        setError('');
      } catch (requestError) {
        if (!mounted.current) return;
        setError(requestError instanceof Error && requestError.name === 'AbortError' ? 'Status request timed out' : requestError instanceof Error ? requestError.message : 'Status request failed');
      } finally {
        window.clearTimeout(timeout);
        if (statusController.current === controller) statusController.current = null;
        if (statusFlight.current === flight) statusFlight.current = null;
      }
    })();
    statusFlight.current = flight;
    return flight;
  }, [applyStatus, mode]);

  useEffect(() => {
    void loadStatus();
  }, [loadStatus]);

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
    try {
      const response = await fetch(`${API}${path}`, {
        method: 'POST', signal: controller.signal,
        ...(body
          ? { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }
          : {}),
      });
      const data = await readCaptureResponse(response, 'Capture request failed');
      applyStatus(data);
    } catch (requestError) {
      setError(requestError instanceof Error && requestError.name === 'AbortError' ? 'Capture request timed out; operation status is being reconciled while polling continues.' : requestError instanceof Error ? requestError.message : 'Capture request failed');
    } finally {
      window.clearTimeout(timeout);
      setBusy(false);
    }
  }, [applyStatus]);

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
  const ap3Ready = ap3Health?.state === 'ready' && !ap3Health.stale;
  const raspiReady = raspiHealth?.state === 'ready' && !raspiHealth.stale;
  const anyActive = isActive(uav.service) || isActive(usrp.service);
  const overallLabel = missionLabel(status);
  const overallTone = status?.overall_state === 'failed'
    ? 'danger'
    : status?.overall_state === 'degraded' || status?.overall_state === 'completed_with_warning'
      ? 'warning'
      : anyActive ? 'live' : 'waiting';
  const uavKnown = uav.connection !== 'unknown' && uav.service !== 'unknown'
    && uav.file !== 'unknown' && uav.phase !== 'unknown';
  const usrpKnown = usrp.connection !== 'unknown' && usrp.service !== 'unknown'
    && usrp.file !== 'unknown' && usrp.phase !== 'unknown';
  const controlsLocked = busy || isUnresolved(uav) || isUnresolved(usrp);
  const bothReady = uavKnown && usrpKnown && ap3Ready && raspiReady;
  const canStartUav = uavKnown && !bind && !busy && !isUnresolved(uav) && ap3Ready;
  const disabledStyle = (disabled: boolean) => ({ opacity: disabled ? 0.45 : 1 });
  const stopAction = (
    target: 'uav' | 'usrp',
    child: ChildState,
    childMissionId: string,
  ) => {
    const retry = canRetryStop(child, Boolean(status?.stop_requested_at));
    const stopped = child.service === 'stopped';
    const raspiUnavailable = target === 'usrp' && !raspiReady;
    const disabled = busy || stopped || (retry ? raspiUnavailable : !canStop(child.service));
    const label = stopped ? 'Stopped' : retry ? 'Retry Stop' : target === 'uav' ? 'Stop UAV' : 'Stop USRP';
    const path = retry
      ? `/api/capture/${target}/retry-stop?mission_id=${encodeURIComponent(childMissionId)}`
      : `/api/capture/${target}/stop?mission_id=${encodeURIComponent(childMissionId)}`;
    return <>
      <button
        type="button"
        style={{ ...S.button, ...S.stop, ...disabledStyle(disabled) }}
        disabled={disabled}
        aria-label={label}
        title={retry && raspiUnavailable ? 'Reconnect Raspberry Pi before retrying stop.' : undefined}
        onClick={() => void request(path)}
      >
        {label}
      </button>
      {retry && raspiUnavailable ? (
        <div aria-live="polite" style={S.error}>Reconnect Raspberry Pi before retrying stop.</div>
      ) : null}
    </>;
  };

  const childSection = (
    title: string,
    child: ChildState,
    actions: React.ReactNode,
    steps: string[],
  ) => (
    <section style={S.section}>
      <div style={S.sectionTitle}>{title}</div>
      <div style={S.rows}>
        <span style={S.key}>Connection</span>
        <span style={S.value}>{CONNECTION_LABELS[child.connection]}</span>
        <span style={S.key}>Phase</span>
        <span style={S.value} aria-live="polite">{PHASE_LABELS[child.phase ?? 'unknown']}</span>
        <span style={S.key}>Service</span>
        <span style={S.value}>{SERVICE_LABELS[child.service]}</span>
        <span style={S.key}>File</span>
        <span style={S.value}>{FILE_LABELS[child.file]}</span>
        {child.last_sample_at ? <>
          <span style={S.key}>Last GPS</span>
          <span style={S.value}>{child.last_sample_at}</span>
        </> : null}
      </div>
      <div style={S.steps} aria-label={`${title} progress`}>
        {steps.map((step, index) => {
          const state = stepState(step, child, index, steps);
          return <div key={step} data-step-state={state}>{STEP_MARKERS[state]} {step} — {state}</div>;
        })}
      </div>
      {child.error ? <div role="alert" style={S.error}>{child.error}</div> : null}
      {child.phase === 'resume_timeout' && child.file === 'ready' ? (
        <div style={S.error}>Partial GPS file available.</div>
      ) : null}
      {child.service === 'presumed_running' ? <div style={S.error}>Presumed running; reconcile status before stopping.</div> : null}
      {child.service === 'stopped' && child.file === 'upload_pending' ? <div style={S.error}>Stopped; upload pending.</div> : null}
      {child.file === 'upload_pending' && title.includes('USRP') ? <button type="button" style={S.button} disabled={busy} onClick={() => void request(`/api/capture/usrp/upload/retry?mission_id=${encodeURIComponent(child.mission_id || missionId)}`)}>Retry upload</button> : null}
      {actions}
    </section>
  );

  return (
    <MinPanel
      title="採樣控制面板"
      className="panel-ui"
      actions={<PanelStatus tone={overallTone} label={overallLabel} />}
    >
      <div style={S.control}>
        <div style={S.topRow}>
          <strong>裝置綁定</strong>
          <button type="button" style={S.button} disabled={busy} onClick={() => void loadStatus()}>Refresh status</button>
          <button
            type="button"
            role="switch"
            aria-label="Bind services"
            aria-checked={bind}
            disabled={controlsLocked || !uavKnown || !usrpKnown}
            style={{ ...S.button, ...(bind ? S.active : null), ...disabledStyle(controlsLocked || !uavKnown || !usrpKnown) }}
            onClick={() => setBind(value => !value)}
          >
            {bind ? '啟用' : '關閉'}
          </button>
        </div>

        <div style={S.health} aria-label="Device Health">
          {(['ap3', 'raspi'] as const).map((device) => {
            const item = health[device];
            const label = device === 'ap3' ? 'AP3' : 'Raspberry Pi';
            const state = item?.stale ? 'unknown' : item?.state ?? 'unknown';
            return (
              <div key={device} style={S.healthCard} aria-label={`${label} Device Health`}>
                <strong>{label}</strong>
                <div style={S.value}>{CONNECTION_LABELS[state]}</div>
                {item?.last_checked_at ? <div>Last check: {item.last_checked_at}</div> : null}
                {item?.error ? <div style={S.error}>{item.error}</div> : null}
              </div>
            );
          })}
        </div>

        {childSection(
          '無人機 GPS 採樣',
          uav,
          <div style={S.actions}>
            <button
              type="button"
              style={{ ...S.button, ...disabledStyle(!canStartUav) }}
              disabled={!canStartUav}
              onClick={() => void request('/api/capture/uav/start')}
            >
              Start UAV
            </button>
            {stopAction('uav', uav, uavMissionId)}
          </div>,
          ['Start recorder', 'Record', 'Stop recorder', 'Finalize CSV', 'Complete'],
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
                  disabled={controlsLocked || !usrpKnown || !raspiReady}
                  style={{
                    ...S.button,
                    ...(mode === value ? S.active : null),
                    ...disabledStyle(controlsLocked || !usrpKnown || !raspiReady),
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
                style={{ ...S.button, ...disabledStyle(bind || busy || !usrpKnown || isUnresolved(usrp) || !raspiReady) }}
                disabled={bind || busy || !usrpKnown || isUnresolved(usrp) || !raspiReady}
                onClick={() => void request('/api/capture/usrp/start', startBody)}
              >
                Start USRP
              </button>
              {stopAction('usrp', usrp, usrpMissionId)}
            </div>
          </>,
          ['Connect', 'Configure', 'Start service', 'Record', 'Stop service', 'Finalize CSV', 'Upload', 'Complete'],
        )}

        {bind ? (
          <div style={S.actions}>
            <button
              type="button"
              style={{ ...S.button, ...S.active, ...disabledStyle(controlsLocked || !bothReady) }}
              disabled={controlsLocked || !bothReady}
              onClick={() => void request('/api/capture/bind/start', startBody)}
            >
              Start Bound Capture
            </button>
            <button
              type="button"
              style={{ ...S.button, ...S.stop, ...disabledStyle(busy || !missionId || !anyActive || Boolean(status?.stop_requested_at)) }}
              disabled={busy || !missionId || !anyActive || Boolean(status?.stop_requested_at)}
              onClick={() => void request(`/api/capture/bind/stop?mission_id=${encodeURIComponent(missionId)}`)}
            >
              Stop All
            </button>
          </div>
        ) : null}

        {missionId ? <div style={S.mission}>Mission: {missionId}</div> : null}
        {error ? <div role="alert" style={S.error}>{error}</div> : null}
      </div>

    </MinPanel>
  );
}
