import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type React from 'react';
import { MinPanel } from './MinPanel';
import { PanelStatus } from './PanelUi';

const API = import.meta.env.VITE_API_URL || '';
type SamplingMode = 'test' | 'usrp';
type ConnectionState = 'ready' | 'offline' | 'unknown';
type ServiceState = 'idle' | 'starting' | 'running' | 'presumed_running' | 'stopping' | 'stopped' | 'failed';
type FileState = 'none' | 'recording' | 'finalizing' | 'ready' | 'upload_pending' | 'uploaded' | 'failed';
type CapturePhase = 'idle' | 'preflight' | 'connecting' | 'configuring' | 'starting_service' | 'recording' | 'stopping_service' | 'finalizing_file' | 'upload_pending' | 'uploading' | 'completed' | 'reconciling' | 'failed';

interface ChildState {
  mission_id: string;
  connection: ConnectionState;
  service: ServiceState;
  file: FileState;
  error: string;
  path: string;
  pid: number | null;
  phase?: CapturePhase;
  last_attempt_at?: string;
  last_success_at?: string;
  refresh_state?: string;
  consecutive_failures?: number;
  next_retry_at?: string;
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
const EMPTY_CHILD: ChildState = { mission_id: '', connection: 'unknown', service: 'idle', file: 'none', error: '', path: '', pid: null, phase: 'idle' };
const PHASE_LABELS: Record<CapturePhase, string> = { idle: 'Idle', preflight: 'Preflight', connecting: 'Connecting', configuring: 'Configuring', starting_service: 'Starting service', recording: 'Recording', stopping_service: 'Stopping service', finalizing_file: 'Finalizing CSV', upload_pending: 'Upload pending', uploading: 'Uploading', completed: 'Complete', reconciling: 'Reconciling presumed-running state', failed: 'Failed' };
const CONNECTION_LABELS: Record<ConnectionState, string> = { ready: 'Ready', offline: 'Offline', unknown: 'Unknown' };
const SERVICE_LABELS: Record<ServiceState, string> = { idle: 'Idle', starting: 'Starting', running: 'Running', presumed_running: 'Presumed running', stopping: 'Stopping', stopped: 'Stopped', failed: 'Failed' };
const FILE_LABELS: Record<FileState, string> = { none: 'None', recording: 'Recording', finalizing: 'Finalizing', ready: 'Ready', upload_pending: 'Pending upload', uploaded: 'Uploaded', failed: 'Failed' };
const S: Record<string, React.CSSProperties> = {
  control: { marginBottom: 10, padding: '10px', borderRadius: 6, background: 'rgba(255, 255, 255, 0.05)', border: '1px solid rgba(120, 180, 255, 0.12)' },
  topRow: { display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8, marginBottom: 10 },
  section: { padding: '9px', marginTop: 8, borderRadius: 6, background: 'rgba(0, 0, 0, 0.16)' }, sectionTitle: { marginBottom: 7, color: '#fff', fontSize: 12, fontWeight: 800 },
  rows: { display: 'grid', gridTemplateColumns: '76px 1fr', gap: '4px 8px', fontSize: 11 }, key: { color: 'rgba(210, 230, 255, 0.55)', textTransform: 'uppercase', letterSpacing: '0.06em' }, value: { color: '#e8f2ff', fontWeight: 700, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' },
  actions: { display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0, 1fr))', gap: 6, marginTop: 8 }, modes: { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6, marginTop: 8 },
  button: { minHeight: 30, minWidth: 0, width: '100%', padding: '0 8px', border: '1px solid rgba(140, 205, 255, 0.22)', borderRadius: 6, background: 'rgba(99, 199, 255, 0.12)', color: '#e8f2ff', fontSize: 11, fontWeight: 700, cursor: 'pointer', transition: 'transform 120ms ease, opacity 120ms ease' }, active: { background: 'rgba(0, 229, 138, 0.18)', borderColor: 'rgba(0, 229, 138, 0.34)' }, stop: { background: 'rgba(255, 116, 116, 0.14)', borderColor: 'rgba(255, 116, 116, 0.26)' }, error: { marginTop: 8, color: '#ffb0b0', fontSize: 11, lineHeight: 1.35 }, warning: { marginTop: 8, color: '#ffd58a', fontSize: 11, lineHeight: 1.35 }, mission: { marginTop: 8, color: 'rgba(210, 230, 255, 0.65)', fontSize: 10, wordBreak: 'break-all' }, steps: { display: 'grid', gap: 3, marginTop: 8, fontSize: 10 }, freshness: { marginTop: 6, color: 'rgba(210, 230, 255, 0.68)', fontSize: 10 },
};
function isActive(service: ServiceState) { return ['starting', 'running', 'presumed_running', 'stopping'].includes(service); }
function canStop(service: ServiceState) { return ['starting', 'running', 'presumed_running'].includes(service); }
function isPollingPhase(phase?: CapturePhase) { return Boolean(phase && !['idle', 'completed', 'failed'].includes(phase)); }
const STEP_PHASES: Record<string, CapturePhase[]> = { 'Start recorder': ['starting_service'], Record: ['recording'], 'Stop recorder': ['stopping_service'], 'Finalize CSV': ['finalizing_file'], Connect: ['connecting'], Configure: ['configuring', 'preflight'], 'Start service': ['starting_service'], 'Stop service': ['stopping_service'], Upload: ['upload_pending', 'uploading'], Complete: ['completed'] };
function stepState(step: string, child: ChildState, index: number, steps: string[]) { const phase = child.phase ?? 'idle'; if (child.error || phase === 'failed' || child.file === 'failed' || child.service === 'failed') return 'error'; if (child.service === 'presumed_running' || phase === 'reconciling') return 'warning'; const currentIndex = steps.findIndex(item => (STEP_PHASES[item] ?? []).includes(phase)); if (phase === 'completed' || (child.file === 'uploaded' && index === steps.length - 1)) return 'completed'; if (phase === 'upload_pending' || phase === 'uploading') return step === 'Upload' ? 'current' : step === 'Complete' ? 'waiting' : index < steps.indexOf('Upload') ? 'completed' : 'waiting'; if (currentIndex >= 0) return index < currentIndex ? 'completed' : index === currentIndex ? 'current' : 'waiting'; return phase === 'idle' ? 'waiting' : index === 0 ? 'current' : 'waiting'; }
const STEP_MARKERS = { completed: '✓', current: '●', waiting: '○', warning: '!', error: '×' };
function normalizeStatus(value: Partial<CaptureStatus>): CaptureStatus { return { mission_id: String(value.mission_id ?? ''), target: value.target === 'usrp' || value.target === 'bind' ? value.target : 'uav', bind: Boolean(value.bind), selected_usrp_mode: value.selected_usrp_mode === 'usrp' ? 'usrp' : 'test', overall_state: String(value.overall_state ?? 'ready'), created_at: String(value.created_at ?? ''), started_at: value.started_at ?? null, finished_at: value.finished_at ?? null, uav: { ...EMPTY_CHILD, ...(value.uav ?? {}) }, usrp: { ...EMPTY_CHILD, ...(value.usrp ?? {}) } }; }
function responseMessage(value: unknown, fallback: string) { if (value && typeof value === 'object') { const body = value as { detail?: unknown; error?: unknown }; if (typeof body.detail === 'string') return body.detail; if (typeof body.error === 'string') return body.error; } return fallback; }
async function readCaptureResponse(response: Response, fallback: string): Promise<Partial<CaptureStatus>> { const raw = await response.text(); let data: unknown = {}; if (raw) { try { data = JSON.parse(raw); } catch (parseError) { if (!response.ok) throw new Error(raw); throw parseError; } } if (!response.ok) throw new Error(responseMessage(data, raw || fallback)); return data as Partial<CaptureStatus>; }

export function USRPTelemetry() {
  const [mode, setMode] = useState<SamplingMode>('test');
  const [bind, setBind] = useState(false); const [status, setStatus] = useState<CaptureStatus | null>(null); const [error, setError] = useState('');
  const [gpsBusyAction, setGpsBusyAction] = useState(false); const [usrpBusyAction, setUsrpBusyAction] = useState(false); const [statusRefreshing, setStatusRefreshing] = useState(false); const [refreshAllBusy, setRefreshAllBusy] = useState(false); const [now, setNow] = useState(() => Date.now());
  const statusRequest = useRef<{ controller: AbortController; generation: number } | null>(null); const generation = useRef(0); const mounted = useRef(true);
  const applyStatus = useCallback((data: Partial<CaptureStatus>, requestGeneration?: number) => { if (requestGeneration !== undefined && requestGeneration !== generation.current) return null; const next = normalizeStatus(data); setStatus(next); if (next.bind && (isActive(next.uav.service) || isActive(next.usrp.service))) setBind(true); if (isActive(next.usrp.service)) setMode(next.selected_usrp_mode); return next; }, []);
  const loadStatus = useCallback(async (manual = false): Promise<CaptureStatus | null> => {
    if (statusRequest.current) { if (!manual) return null; statusRequest.current.controller.abort(); }
    const controller = new AbortController(); const requestGeneration = ++generation.current; statusRequest.current = { controller, generation: requestGeneration }; const timeout = window.setTimeout(() => controller.abort(), 5000); setStatusRefreshing(true);
    try { const response = await fetch(`${API}/api/capture/status?usrp_mode=${mode}`, { signal: controller.signal }); const data = await readCaptureResponse(response, 'Status request failed'); const next = applyStatus(data, requestGeneration); if (mounted.current) setError(''); return next; }
    catch (requestError) { if (mounted.current && requestGeneration === generation.current && requestError instanceof Error && requestError.name !== 'AbortError') setError(requestError.message); else if (mounted.current && requestGeneration === generation.current && requestError instanceof Error) setError('Status request timed out'); return null; }
    finally { window.clearTimeout(timeout); if (statusRequest.current?.generation === requestGeneration) statusRequest.current = null; if (mounted.current) setStatusRefreshing(false); }
  }, [applyStatus, mode]);
  useEffect(() => { mounted.current = true; void loadStatus(); const timer = window.setInterval(() => void loadStatus(), 3000); const clock = window.setInterval(() => setNow(Date.now()), 1000); return () => { mounted.current = false; window.clearInterval(timer); window.clearInterval(clock); statusRequest.current?.controller.abort(); statusRequest.current = null; }; }, [loadStatus]);
  const request = useCallback(async (path: string, body?: object, device: 'gps' | 'usrp' | 'both' = 'gps', deadline = 45000) => {
    const controller = new AbortController(); const timeout = window.setTimeout(() => controller.abort(), deadline); const requestGeneration = ++generation.current; if (device === 'gps') setGpsBusyAction(true); else if (device === 'usrp') setUsrpBusyAction(true); else { setGpsBusyAction(true); setUsrpBusyAction(true); } setError('');
    try { const response = await fetch(`${API}${path}`, { method: 'POST', signal: controller.signal, ...(body ? { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) } : {}) }); const data = await readCaptureResponse(response, 'Capture request failed'); applyStatus(data, requestGeneration); }
    catch (requestError) { if (mounted.current) setError(requestError instanceof Error && requestError.name === 'AbortError' ? 'Capture request timed out; operation status is being reconciled while polling continues.' : requestError instanceof Error ? requestError.message : 'Capture request failed'); }
    finally { window.clearTimeout(timeout); if (device === 'gps') setGpsBusyAction(false); else if (device === 'usrp') setUsrpBusyAction(false); else { setGpsBusyAction(false); setUsrpBusyAction(false); } }
  }, [applyStatus]);
  const refreshAll = useCallback(async () => {
    if (refreshAllBusy) return;
    setRefreshAllBusy(true);
    try {
      const snapshot = await loadStatus(true);
      const refreshMissionId = snapshot?.usrp.mission_id || snapshot?.mission_id || '';
      await request('/api/capture/gps/refresh', undefined, 'gps', 30000);
      if (refreshMissionId) await request(`/api/capture/usrp/refresh?mission_id=${encodeURIComponent(refreshMissionId)}`, undefined, 'usrp', 30000);
    } finally {
      setRefreshAllBusy(false);
    }
  }, [loadStatus, refreshAllBusy, request]);
  const startBody = useMemo(() => ({ usrp_mode: mode, scene: 'NTPU', map_type: 'iss' }), [mode]); const uav = status?.uav ?? EMPTY_CHILD; const usrp = status?.usrp ?? EMPTY_CHILD; const missionId = status?.mission_id ?? ''; const uavMissionId = uav.mission_id || missionId; const usrpMissionId = usrp.mission_id || missionId; const anyActive = isActive(uav.service) || isActive(usrp.service); const bothReady = uav.connection === 'ready' && usrp.connection === 'ready'; const anyBusy = gpsBusyAction || usrpBusyAction || statusRefreshing;
  const freshness = (child: ChildState) => { const timestamp = child.last_success_at || child.last_attempt_at; const retry = child.next_retry_at ? Math.max(0, Math.ceil((Date.parse(child.next_retry_at) - now) / 1000)) : null; return <div style={S.freshness}>{timestamp ? `Last seen ${timestamp}` : 'Last known state unavailable'}{retry !== null ? ` · Retry in ${retry}s` : ''}</div>; };
  const gpsLabel = gpsBusyAction ? (isActive(uav.service) ? 'Stopping GPS…' : 'Starting GPS…') : uav.connection !== 'ready' ? 'GPS status unconfirmed' : uav.service === 'starting' ? 'Starting GPS…' : uav.service === 'stopping' ? 'Stopping GPS…' : uav.phase === 'finalizing_file' ? 'Finalizing GPS…' : isActive(uav.service) ? 'Stop GPS · Recording' : 'Start GPS';
  const usrpLabel = usrpBusyAction ? (isActive(usrp.service) ? 'Stopping service…' : 'Starting USRP…') : usrp.connection !== 'ready' && canStop(usrp.service) ? 'Stop unconfirmed' : usrp.service === 'starting' || ['connecting', 'configuring'].includes(usrp.phase ?? '') ? `${PHASE_LABELS[usrp.phase ?? 'starting_service']}…` : usrp.service === 'stopping' ? 'Stopping service…' : usrp.phase === 'finalizing_file' ? 'Saving CSV…' : usrp.file === 'upload_pending' && usrp.service === 'stopped' ? 'Retry unavailable · CSV saved' : isActive(usrp.service) ? 'Stop USRP · Recording' : 'Start USRP';
  const disabledStyle = (disabled: boolean) => ({ opacity: disabled ? 0.45 : 1 });
  const childSection = (title: string, child: ChildState, actions: React.ReactNode, steps: string[]) => <section style={S.section} aria-label={title}><div style={S.sectionTitle}>{title}</div><div style={S.rows}><span style={S.key}>Connection</span><span style={S.value}>{CONNECTION_LABELS[child.connection]}</span><span style={S.key}>Phase</span><span style={S.value} aria-live="polite">{PHASE_LABELS[child.phase ?? 'idle']}</span><span style={S.key}>Service</span><span style={S.value}>{SERVICE_LABELS[child.service]}</span><span style={S.key}>File</span><span style={S.value}>{FILE_LABELS[child.file]}</span></div>{freshness(child)}{child.connection === 'offline' || child.refresh_state === 'retry_wait' ? <div style={S.warning}>Offline or retrying; showing last-known service and file state.</div> : null}<details open><summary>Progress details</summary><div style={S.steps} aria-label={`${title} progress`}>{steps.map((step, index) => { const state = stepState(step, child, index, steps) as keyof typeof STEP_MARKERS; return <div key={step} data-step-state={state}>{STEP_MARKERS[state]} {step} — {state}</div>; })}</div></details>{child.error ? <div role="alert" style={S.error}>{child.error}</div> : null}{child.service === 'presumed_running' ? <div style={S.warning}>Presumed running; reconcile status before stopping.</div> : null}{child.service === 'stopped' && child.file === 'upload_pending' ? <div style={S.warning}>Retry unavailable · CSV saved; refresh status manually.</div> : null}{actions}</section>;
  return <MinPanel title="採樣控制面板" className="panel-ui" actions={<PanelStatus tone={anyActive ? 'live' : 'waiting'} label={anyActive ? 'Active' : 'Ready'} />}><style>{`.panel-ui button:active { transform: scale(.97); } @media (prefers-reduced-motion: reduce) { .panel-ui button { transition: none !important; } }`}</style><div style={S.control}><div style={S.topRow}><strong>裝置綁定</strong><button type="button" style={{ ...S.button, ...disabledStyle(statusRefreshing || refreshAllBusy) }} disabled={statusRefreshing || refreshAllBusy} aria-busy={statusRefreshing || refreshAllBusy} onClick={() => void refreshAll()}>{statusRefreshing || refreshAllBusy ? 'Checking…' : 'Refresh all'}</button><button type="button" role="switch" aria-label="Bind services" aria-checked={bind} disabled={anyBusy || anyActive} style={{ ...S.button, ...(bind ? S.active : null), ...disabledStyle(anyBusy || anyActive) }} onClick={() => setBind(value => !value)}>{bind ? '啟用' : '關閉'}</button></div>
    {childSection('無人機 GPS 採樣', uav, <><div style={S.actions}>{isActive(uav.service) ? <button type="button" style={{ ...S.button, ...S.stop, ...disabledStyle(gpsBusyAction || !canStop(uav.service) || uav.service === 'starting' || uav.service === 'stopping' || uav.connection !== 'ready') }} disabled={gpsBusyAction || !canStop(uav.service) || uav.service === 'starting' || uav.service === 'stopping' || uav.connection !== 'ready'} aria-busy={gpsBusyAction} onClick={() => void request(`/api/capture/uav/stop?mission_id=${encodeURIComponent(uavMissionId)}`, undefined, 'gps')}>{gpsLabel}</button> : <button type="button" style={{ ...S.button, ...disabledStyle(bind || gpsBusyAction || uav.connection !== 'ready' || isActive(uav.service) || uav.phase === 'finalizing_file') }} disabled={bind || gpsBusyAction || uav.connection !== 'ready' || isActive(uav.service) || uav.phase === 'finalizing_file'} aria-busy={gpsBusyAction} onClick={() => void request('/api/capture/uav/start', undefined, 'gps')}>{gpsLabel}</button>}</div><button type="button" style={S.button} disabled={gpsBusyAction} aria-busy={gpsBusyAction} onClick={() => void request('/api/capture/gps/refresh', undefined, 'gps', 30000)}>{gpsBusyAction ? 'Checking…' : 'Refresh GPS'}</button></>, ['Start recorder', 'Record', 'Stop recorder', 'Finalize CSV', 'Complete'])}
    {childSection('USRP 干擾採樣', usrp, <><div style={S.modes} aria-label="USRP capture mode">{(['test', 'usrp'] as SamplingMode[]).map(value => <button key={value} type="button" aria-label={value === 'test' ? 'Test mode' : 'USRP mode'} aria-pressed={mode === value} disabled={usrpBusyAction || isActive(usrp.service)} style={{ ...S.button, ...(mode === value ? S.active : null), ...disabledStyle(usrpBusyAction || isActive(usrp.service)) }} onClick={() => setMode(value)}>{value === 'test' ? 'Test' : 'USRP'}</button>)}</div><div style={S.actions}>{isActive(usrp.service) ? <button type="button" style={{ ...S.button, ...S.stop, ...disabledStyle(usrpBusyAction || !canStop(usrp.service) || usrp.connection !== 'ready') }} disabled={usrpBusyAction || !canStop(usrp.service) || usrp.connection !== 'ready'} aria-busy={usrpBusyAction} onClick={() => void request(`/api/capture/usrp/stop?mission_id=${encodeURIComponent(usrpMissionId)}`, undefined, 'usrp')}>{usrpLabel}</button> : <button type="button" style={{ ...S.button, ...disabledStyle(bind || usrpBusyAction || isActive(usrp.service) || usrp.connection !== 'ready' || usrp.phase === 'finalizing_file' || (usrp.file === 'upload_pending' && usrp.service === 'stopped')) }} disabled={bind || usrpBusyAction || isActive(usrp.service) || usrp.connection !== 'ready' || usrp.phase === 'finalizing_file' || (usrp.file === 'upload_pending' && usrp.service === 'stopped')} aria-busy={usrpBusyAction} onClick={() => void request('/api/capture/usrp/start', startBody, 'usrp')}>{usrpLabel}</button>}</div><button type="button" style={S.button} disabled={usrpBusyAction} aria-busy={usrpBusyAction} onClick={() => void request(`/api/capture/usrp/refresh?mission_id=${encodeURIComponent(usrpMissionId)}`, undefined, 'usrp', 30000)}>{usrpBusyAction ? 'Checking…' : 'Refresh USRP'}</button></>, ['Connect', 'Configure', 'Start service', 'Record', 'Stop service', 'Finalize CSV', 'Upload', 'Complete'])}
    {bind ? <div style={S.actions}><button type="button" style={{ ...S.button, ...S.active, ...disabledStyle(anyBusy || anyActive || !bothReady) }} disabled={anyBusy || anyActive || !bothReady} aria-busy={gpsBusyAction && usrpBusyAction} onClick={() => void request('/api/capture/bind/start', startBody, 'both')}>Start Bound Capture</button><button type="button" style={{ ...S.button, ...S.stop, ...disabledStyle(anyBusy || !missionId || !anyActive) }} disabled={anyBusy || !missionId || !anyActive} aria-busy={gpsBusyAction && usrpBusyAction} onClick={() => void request(`/api/capture/bind/stop?mission_id=${encodeURIComponent(missionId)}`, undefined, 'both')}>Stop All</button></div> : null}{missionId ? <div style={S.mission}>Mission: {missionId} · {status?.overall_state}</div> : null}{error ? <div role="alert" style={S.error}>{error}</div> : null}</div></MinPanel>;
}
