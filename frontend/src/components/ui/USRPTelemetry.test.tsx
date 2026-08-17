import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { formatTaipeiTime, USRPTelemetry } from './USRPTelemetry';

type ChildOverrides = {
  connection?: string;
  service?: string;
  file?: string;
  phase?: string;
  error?: string;
  last_sample_at?: string | null;
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
};

function captureStatus(options: {
  missionId?: string;
  bind?: boolean;
  mode?: 'test' | 'usrp';
  overall?: string;
  stopRequestedAt?: string | null;
  uav?: ChildOverrides;
  usrp?: ChildOverrides;
} = {}) {
  const child = (overrides: ChildOverrides = {}) => ({
    mission_id: options.missionId ?? '',
    connection: 'ready',
    service: 'idle',
    file: 'none',
    phase: 'idle',
    error: '',
    path: '',
    pid: null,
    ...overrides,
  });
  return {
    mission_id: options.missionId ?? '',
    target: options.bind ? 'bind' : 'uav',
    bind: options.bind ?? false,
    selected_usrp_mode: options.mode ?? 'test',
    overall_state: options.overall ?? 'ready',
    created_at: '2026-06-24T00:00:00Z',
    started_at: null,
    finished_at: null,
    stop_requested_at: options.stopRequestedAt ?? null,
    uav: child(options.uav),
    usrp: child(options.usrp),
    device_health: {
      ap3: {
        device: 'ap3', state: 'ready', checked_at: '2026-06-24T00:00:00Z',
        last_checked_at: '2026-06-24T00:00:00Z', next_check_at: null,
        retry_delay: 10, stale: false, error: '',
      },
      raspi: {
        device: 'raspi', state: 'ready', checked_at: '2026-06-24T00:00:00Z',
        last_checked_at: '2026-06-24T00:00:00Z', next_check_at: null,
        retry_delay: 10, stale: false, error: '',
      },
    },
  };
}

function jsonResponse(payload: unknown, ok = true) {
  return Promise.resolve({
    ok,
    json: () => Promise.resolve(payload),
    text: () => Promise.resolve(JSON.stringify(payload)),
  } as Response);
}

function textResponse(payload: string, ok = false) {
  return Promise.resolve({
    ok,
    json: () => Promise.reject(new SyntaxError(`Unexpected token 'I', "${payload.slice(0, 10)}"... is not valid JSON`)),
    text: () => Promise.resolve(payload),
  } as Response);
}

async function openTelemetry() {
  const user = userEvent.setup();
  render(<USRPTelemetry />);
  return user;
}

describe('USRPTelemetry capture controls', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn(() => jsonResponse(captureStatus())));
  });

  afterEach(() => {
    cleanup();
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it('defaults Bind off and exposes independent UAV and USRP controls', async () => {
    render(<USRPTelemetry />);

    expect(screen.getByRole('button', { name: '收合 採樣控制面板' }))
      .toHaveAttribute('aria-expanded', 'true');

    expect(await screen.findByText('無人機 GPS 採樣')).toBeInTheDocument();
    expect(screen.getByText('Noise 採樣')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '綁定任務模式' }))
      .toHaveAttribute('aria-pressed', 'false');
    expect(await screen.findByRole('button', { name: '開始 GPS 採樣' })).toBeEnabled();
    expect(await screen.findByRole('button', { name: '開始 Noise 採樣' })).toBeEnabled();
    expect(globalThis.fetch).toHaveBeenCalledWith(
      '/api/capture/status?usrp_mode=test',
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
  });

  it('renders AP3 and Raspberry Pi Device Health independently from mission children', async () => {
    const status = captureStatus({ missionId: 'history_1' });
    status.uav.connection = 'ready';
    status.usrp.connection = 'ready';
    (status as typeof status & { device_health: object }).device_health = {
      ap3: {
        device: 'ap3', state: 'offline', checked_at: '2026-08-12T00:00:00Z',
        last_checked_at: '2026-08-12T00:00:00Z', next_check_at: null,
        retry_delay: 5, stale: false, error: 'USB disconnected',
      },
      raspi: {
        device: 'raspi', state: 'ready', checked_at: '2026-08-12T00:00:00Z',
        last_checked_at: '2026-08-12T00:00:00Z', next_check_at: null,
        retry_delay: 10, stale: false, error: '',
      },
    };
    vi.mocked(globalThis.fetch).mockImplementation(() => jsonResponse(status));

    await openTelemetry();

    expect(await screen.findByLabelText('AP3 裝置就緒')).toHaveTextContent('離線');
    expect(screen.getByLabelText('Raspberry Pi 裝置就緒')).toHaveTextContent('就緒');
    expect(screen.getByText('USB disconnected')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '開始 GPS 採樣' })).toBeDisabled();
    expect(screen.getByRole('button', { name: '開始 Noise 採樣' })).toBeEnabled();
    const healthGrid = screen.getByLabelText('裝置就緒');
    expect(healthGrid).toHaveStyle({ gridTemplateColumns: 'minmax(0, 1fr) minmax(0, 1fr)' });
    expect(screen.getByLabelText('AP3 裝置就緒')).toHaveStyle({ minWidth: '0', overflowWrap: 'anywhere' });
  });

  it('treats stale health as unknown and keeps it separate from a terminal child', async () => {
    const status = captureStatus({ missionId: 'history_2', overall: 'completed' });
    status.uav.service = 'stopped';
    status.uav.file = 'ready';
    (status as typeof status & { device_health: object }).device_health = {
      ap3: {
        device: 'ap3', state: 'ready', checked_at: '2026-08-11T23:00:00Z',
        last_checked_at: '2026-08-11T23:00:00Z', next_check_at: null,
        retry_delay: 10, stale: true, error: 'ap3 health result is stale',
      },
      raspi: {
        device: 'raspi', state: 'ready', checked_at: '2026-08-12T00:00:00Z',
        last_checked_at: '2026-08-12T00:00:00Z', next_check_at: null,
        retry_delay: 10, stale: false, error: '',
      },
    };
    vi.mocked(globalThis.fetch).mockImplementation(() => jsonResponse(status));

    await openTelemetry();

    expect(await screen.findByLabelText('AP3 裝置就緒')).toHaveTextContent('未知');
    expect(screen.getByText('已完成')).toBeInTheDocument();
    expect(screen.getByText('ap3 health result is stale')).toBeInTheDocument();
  });

  it('does not let an old failed child bypass a fresh AP3 health failure', async () => {
    const status = captureStatus({ missionId: 'old_failed', overall: 'failed', uav: { service: 'failed', file: 'failed' } });
    status.device_health.ap3.state = 'offline';
    status.device_health.ap3.error = 'USB disconnected';
    vi.mocked(globalThis.fetch).mockImplementation(() => jsonResponse(status));

    await openTelemetry();

    expect(await screen.findByRole('button', { name: '開始 GPS 採樣' })).toBeDisabled();
    expect(screen.getByLabelText('AP3 裝置就緒')).toHaveTextContent('離線');
  });

  it('marks a hanging health probe unknown after its timeout', async () => {
    vi.useFakeTimers();
    vi.mocked(globalThis.fetch).mockImplementation((input, init) => {
      if (String(input).includes('/api/capture/health')) return new Promise<Response>((_resolve, reject) => {
        init?.signal?.addEventListener('abort', () => {
          const error = new Error('aborted');
          error.name = 'AbortError';
          reject(error);
        });
      });
      return jsonResponse(captureStatus({ missionId: 'health_timeout' }));
    });

    render(<USRPTelemetry />);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(8000);
    });

    expect(screen.getByLabelText('AP3 裝置就緒')).toHaveTextContent('未知');
    expect(screen.getByLabelText('Raspberry Pi 裝置就緒')).toHaveTextContent('未知');
    vi.useRealTimers();
  });

  it('refreshes recovered Device Health without a page reload', async () => {
    vi.useFakeTimers();
    const offline = captureStatus();
    offline.device_health.ap3.state = 'offline';
    offline.device_health.ap3.error = 'USB disconnected';
    const recovered = captureStatus();
    let healthCalls = 0;
    vi.mocked(globalThis.fetch).mockImplementation((input) => {
      if (String(input).includes('/api/capture/health')) {
        healthCalls += 1;
        return jsonResponse(healthCalls === 1 ? offline : recovered);
      }
      return jsonResponse(captureStatus());
    });

    render(<USRPTelemetry />);
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(screen.getByLabelText('AP3 裝置就緒')).toHaveTextContent('離線');

    await act(async () => {
      await vi.advanceTimersByTimeAsync(10000);
    });

    expect(screen.getByLabelText('AP3 裝置就緒')).toHaveTextContent('就緒');
    expect(healthCalls).toBeGreaterThanOrEqual(2);
    vi.useRealTimers();
  });

  it('starts USRP independently when UAV is offline', async () => {
    vi.mocked(globalThis.fetch).mockImplementation((input, init) => {
      if (String(input).includes('/api/capture/usrp/start')) {
        return jsonResponse(captureStatus({
          missionId: 'noise_1',
          mode: 'usrp',
          uav: { connection: 'offline' },
          usrp: { service: 'running', file: 'recording' },
        }));
      }
      return jsonResponse(captureStatus({
        mode: 'usrp',
        uav: { connection: 'offline' },
      }));
    });
    const user = await openTelemetry();

    await user.click(await screen.findByRole('button', { name: 'USRP 模式' }));
    await user.click(screen.getByRole('button', { name: '開始 Noise 採樣' }));

    await waitFor(() => expect(globalThis.fetch).toHaveBeenCalledWith(
      '/api/capture/usrp/start',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ usrp_mode: 'usrp', scene: 'NTPU', map_type: 'iss' }),
      }),
    ));
  });

  it('refreshes the full projection after starting GPS', async () => {
    const idle = captureStatus();
    const started = captureStatus({
      missionId: 'gps_1',
      uav: { service: 'running', file: 'recording', phase: 'recording' },
      usrp: { connection: 'unknown' },
    });
    const projection = captureStatus({
      overall: 'running',
      uav: { service: 'running', file: 'recording', phase: 'recording' },
      usrp: { connection: 'ready' },
    });
    projection.mission_id = '';
    projection.uav.mission_id = 'gps_1';
    let statusCalls = 0;
    vi.mocked(globalThis.fetch).mockImplementation((input) => {
      const url = String(input);
      if (url.includes('/api/capture/uav/start')) return jsonResponse(started);
      if (url.includes('/api/capture/status')) {
        statusCalls += 1;
        return jsonResponse(statusCalls === 1 ? idle : {
          ...projection,
          control_mode: 'independent',
          active: projection,
        });
      }
      return jsonResponse(idle);
    });
    const user = await openTelemetry();

    await user.click(await screen.findByRole('button', { name: '開始 GPS 採樣' }));

    await waitFor(() => expect(statusCalls).toBeGreaterThan(1));
    expect(screen.getByRole('button', { name: '開始 Noise 採樣' })).toBeEnabled();
  });

  it('refreshes the full projection after starting Noise', async () => {
    const idle = captureStatus();
    const started = captureStatus({
      missionId: 'noise_1',
      mode: 'usrp',
      uav: { connection: 'unknown' },
      usrp: { service: 'running', file: 'recording', phase: 'recording' },
    });
    const projection = captureStatus({
      mode: 'usrp',
      overall: 'running',
      uav: { connection: 'ready' },
      usrp: { service: 'running', file: 'recording', phase: 'recording' },
    });
    projection.mission_id = '';
    projection.usrp.mission_id = 'noise_1';
    let statusCalls = 0;
    vi.mocked(globalThis.fetch).mockImplementation((input) => {
      const url = String(input);
      if (url.includes('/api/capture/usrp/start')) return jsonResponse(started);
      if (url.includes('/api/capture/status')) {
        statusCalls += 1;
        return jsonResponse(statusCalls === 1 ? idle : {
          ...projection,
          control_mode: 'independent',
          active: projection,
        });
      }
      return jsonResponse(idle);
    });
    const user = await openTelemetry();

    await user.click(await screen.findByRole('button', { name: '開始 Noise 採樣' }));

    await waitFor(() => expect(statusCalls).toBeGreaterThan(1));
    expect(screen.getByRole('button', { name: '開始 GPS 採樣' })).toBeEnabled();
  });

  it('queues a fresh status after starting Noise during a status refresh', async () => {
    const initial = captureStatus({
      missionId: 'gps_1',
      overall: 'running',
      uav: { service: 'running', file: 'recording', phase: 'recording' },
      usrp: { connection: 'ready' },
    });
    const stale = captureStatus({
      missionId: 'gps_1',
      overall: 'running',
      uav: { service: 'running', file: 'recording', phase: 'recording' },
      usrp: { connection: 'unknown' },
    });
    const started = captureStatus({
      missionId: 'noise_1',
      uav: { connection: 'unknown' },
      usrp: { service: 'running', file: 'recording', phase: 'recording' },
    });
    const merged = captureStatus({
      overall: 'running',
      uav: { service: 'running', file: 'recording', phase: 'recording' },
      usrp: { service: 'running', file: 'recording', phase: 'recording' },
    });
    merged.mission_id = '';
    merged.uav.mission_id = 'gps_1';
    merged.usrp.mission_id = 'noise_1';
    let statusCalls = 0;
    let releaseStale!: () => void;
    const staleResponse = new Promise<Response>((resolve) => {
      releaseStale = () => {
        void jsonResponse({ ...stale, control_mode: 'independent', active: stale }).then(resolve);
      };
    });
    vi.mocked(globalThis.fetch).mockImplementation((input) => {
      const url = String(input);
      if (url.includes('/api/capture/usrp/start')) return jsonResponse(started);
      if (url.includes('/api/capture/status')) {
        statusCalls += 1;
        if (statusCalls === 1) return jsonResponse({ ...initial, control_mode: 'independent', active: initial });
        if (statusCalls === 2) return staleResponse;
        return jsonResponse({ ...merged, control_mode: 'independent', active: merged });
      }
      return jsonResponse(initial);
    });
    const user = await openTelemetry();

    await user.click(await screen.findByRole('button', { name: '重新整理狀態' }));
    await user.click(screen.getByRole('button', { name: '開始 Noise 採樣' }));
    releaseStale();

    await waitFor(() => expect(statusCalls).toBe(3));
    expect(screen.getByRole('button', { name: '停止 Noise 採樣' })).toBeEnabled();
    expect(screen.queryByText('Noise 任務狀態尚未就緒')).toBeNull();
  });

  it('uses a shared Bind start only when both services are ready', async () => {
    const user = await openTelemetry();

    await user.click(await screen.findByRole('button', { name: '綁定任務模式' }));
    await user.click(screen.getByRole('button', { name: '開始綁定任務' }));

    await waitFor(() => expect(globalThis.fetch).toHaveBeenCalledWith(
      '/api/capture/bind/start',
      expect.objectContaining({ method: 'POST' }),
    ));
    expect(screen.queryByRole('button', { name: '開始 GPS 採樣' })).toBeNull();
    expect(screen.queryByRole('button', { name: '開始 Noise 採樣' })).toBeNull();
  });

  it('selects Noise mode before starting an idle Bound mission', async () => {
    const user = await openTelemetry();

    await user.click(await screen.findByRole('button', { name: '綁定任務模式' }));
    expect(screen.getByRole('button', { name: 'USRP 模式' })).toBeEnabled();

    await user.click(screen.getByRole('button', { name: 'USRP 模式' }));
    await user.click(screen.getByRole('button', { name: '開始綁定任務' }));

    await waitFor(() => expect(globalThis.fetch).toHaveBeenCalledWith(
      '/api/capture/bind/start',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ usrp_mode: 'usrp', scene: 'NTPU', map_type: 'iss' }),
      }),
    ));
  });

  it('keeps mode switching interactive and explains an active Noise task', async () => {
    vi.mocked(globalThis.fetch).mockImplementation(() => jsonResponse(captureStatus({
      missionId: 'noise_2',
      mode: 'usrp',
      usrp: { service: 'running', file: 'recording' },
    })));

    const user = await openTelemetry();

    const bindSwitch = await screen.findByRole('button', { name: '綁定任務模式' });
    expect(bindSwitch).toBeEnabled();
    expect(screen.getByRole('button', { name: '測試模式' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'USRP 模式' })).toBeDisabled();

    await user.click(bindSwitch);

    expect(screen.getByRole('alert')).toHaveTextContent('請先停止 Noise 任務。');
    expect(bindSwitch).toHaveAttribute('aria-pressed', 'false');
    expect(vi.mocked(globalThis.fetch).mock.calls.some(([input]) => String(input).includes('/stop'))).toBe(false);
  });

  it('keeps the mode switch available when an active GPS mission has unknown Noise health', async () => {
    const status = captureStatus({
      missionId: 'gps_health_unknown',
      uav: { service: 'running', file: 'recording' },
      usrp: { connection: 'unknown' },
    });
    status.device_health.raspi.state = 'unknown';
    status.device_health.raspi.stale = true;
    vi.mocked(globalThis.fetch).mockImplementation(() => jsonResponse(status));
    const user = await openTelemetry();

    const bindSwitch = await screen.findByRole('button', { name: '綁定任務模式' });
    expect(bindSwitch).toBeEnabled();
    await user.click(bindSwitch);

    expect(screen.getByRole('alert')).toHaveTextContent('請先停止 GPS 任務。');
  });

  it.each([
    ['GPS', { uav: { service: 'running', file: 'recording' } }, '請先停止 GPS 任務。'],
    ['GPS and Noise', {
      uav: { service: 'running', file: 'recording' },
      usrp: { service: 'running', file: 'recording' },
    }, '請先停止 GPS 與 Noise 任務。'],
    ['Noise upload', {
      usrp: { service: 'stopped', file: 'upload_pending' },
    }, '請先等待 Noise 上傳。'],
  ])('shows the %s mode-switch blocker', async (_name, overrides, notice) => {
    vi.mocked(globalThis.fetch).mockImplementation(() => jsonResponse(captureStatus(overrides)));
    const user = await openTelemetry();

    await user.click(await screen.findByRole('button', { name: '綁定任務模式' }));

    expect(screen.getByRole('alert')).toHaveTextContent(notice);
    expect(screen.getByRole('button', { name: '綁定任務模式' })).toHaveAttribute('aria-pressed', 'false');
  });

  it('uses the Bound task blocker while an active Bound Mission is displayed', async () => {
    vi.mocked(globalThis.fetch).mockImplementation(() => jsonResponse(captureStatus({
      missionId: 'bound_2',
      bind: true,
      overall: 'running',
      uav: { service: 'running', file: 'recording' },
      usrp: { service: 'running', file: 'recording' },
    })));
    const user = await openTelemetry();

    const bindSwitch = await screen.findByRole('button', { name: '綁定任務模式' });
    expect(bindSwitch).toHaveAttribute('aria-pressed', 'true');
    await user.click(bindSwitch);

    expect(screen.getByRole('alert')).toHaveTextContent('請先停止當前任務。');
    expect(bindSwitch).toHaveAttribute('aria-pressed', 'true');
  });

  it.each([
    ['completed', 'completed'],
    ['failed', 'failed'],
  ])('allows switching after a %s result', async (_name, overall) => {
    vi.mocked(globalThis.fetch).mockImplementation(() => jsonResponse(captureStatus({
      missionId: `terminal_${overall}`,
      overall,
      uav: { service: overall === 'completed' ? 'stopped' : 'failed', file: overall === 'completed' ? 'ready' : 'failed' },
    })));
    const user = await openTelemetry();

    const bindSwitch = await screen.findByRole('button', { name: '綁定任務模式' });
    await user.click(bindSwitch);

    expect(bindSwitch).toHaveAttribute('aria-pressed', 'true');
    expect(screen.queryByRole('alert')).toBeNull();
  });

  it('shows presumed running and pending upload without reporting completion', async () => {
    vi.mocked(globalThis.fetch).mockImplementation(() => jsonResponse(captureStatus({
      missionId: 'noise_3',
      overall: 'finalizing',
      usrp: {
        connection: 'offline',
        service: 'presumed_running',
        file: 'upload_pending',
      },
    })));

    await openTelemetry();

    expect(await screen.findByText('推定執行中')).toBeInTheDocument();
    expect(screen.getByText('等待上傳')).toBeInTheDocument();
    expect(screen.queryByText('已完成')).not.toBeInTheDocument();
  });

  it('drives the mission badge from the canonical overall state', async () => {
    vi.mocked(globalThis.fetch).mockImplementation(() => jsonResponse(captureStatus({
      missionId: 'bound_degraded',
      bind: true,
      overall: 'degraded',
      uav: { service: 'failed', file: 'failed' },
      usrp: { service: 'running', file: 'recording' },
    })));

    await openTelemetry();

    expect(await screen.findByText('狀態異常')).toBeInTheDocument();
    expect(screen.getByText('GPS 失敗')).toBeInTheDocument();
  });

  it('prioritizes offline over uncertain degraded reasons', async () => {
    vi.mocked(globalThis.fetch).mockImplementation(() => jsonResponse(captureStatus({
      missionId: 'bound_offline',
      bind: true,
      overall: 'degraded',
      uav: { connection: 'ready', service: 'presumed_running', file: 'recording' },
      usrp: { connection: 'offline', service: 'presumed_running', file: 'recording' },
    })));

    await openTelemetry();

    expect(await screen.findByText('狀態異常')).toBeInTheDocument();
    expect(screen.getByText('Noise 離線')).toBeInTheDocument();
  });

  it('keeps Noise mode selection enabled while GPS is recording', async () => {
    vi.mocked(globalThis.fetch).mockImplementation(() => jsonResponse(captureStatus({
      missionId: 'gps_active',
      overall: 'running',
      uav: { service: 'running', file: 'recording', phase: 'recording' },
    })));

    await openTelemetry();

    expect(await screen.findByRole('button', { name: '測試模式' })).toBeEnabled();
    expect(screen.getByRole('button', { name: 'USRP 模式' })).toBeEnabled();
    expect(screen.getByRole('button', { name: '開始 Noise 採樣' })).toBeEnabled();
  });

  it('shows GPS offline while Noise keeps recording after freshness loss', async () => {
    vi.mocked(globalThis.fetch).mockImplementation(() => jsonResponse(captureStatus({
      missionId: 'gps_stale',
      bind: true,
      overall: 'degraded',
      uav: {
        connection: 'offline',
        service: 'presumed_running',
        file: 'recording',
        phase: 'reconciling',
        error: 'GPS sample is stale',
      },
      usrp: { service: 'running', file: 'recording' },
    })));

    await openTelemetry();

    expect(await screen.findByText('狀態異常')).toBeInTheDocument();
    expect(screen.getByText('GPS 離線')).toBeInTheDocument();
    expect(screen.getAllByText('GPS sample is stale').length).toBeGreaterThan(0);
    expect(screen.getByText('推定執行中')).toBeInTheDocument();
  });

  it('shows AP3 Resume Timeout and the available Partial GPS Result while Noise continues', async () => {
    vi.mocked(globalThis.fetch).mockImplementation(() => jsonResponse(captureStatus({
      missionId: 'resume_timeout',
      bind: true,
      overall: 'degraded',
      uav: {
        service: 'failed',
        file: 'ready',
        phase: 'resume_timeout',
        error: 'AP3 Resume Timeout; partial GPS file available',
      },
      usrp: { service: 'running', file: 'recording' },
    })));

    await openTelemetry();

    expect(await screen.findByText('狀態異常')).toBeInTheDocument();
    expect(screen.getByText('可用的部分 GPS 檔案。')).toBeInTheDocument();
    expect(screen.getByText('AP3 Resume Timeout; partial GPS file available')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '恢復 GPS 採樣' })).toBeNull();
  });

  it('offers GPS recovery for a resume-timeout mission', async () => {
    const status = captureStatus({
      missionId: 'resume_recovery',
      uav: {
        service: 'failed',
        file: 'ready',
        phase: 'resume_timeout',
      },
    });
    vi.mocked(globalThis.fetch).mockImplementation(() => jsonResponse(status));
    const user = await openTelemetry();

    await user.click(await screen.findByRole('button', { name: '恢復 GPS 採樣' }));

    expect(globalThis.fetch).toHaveBeenCalledWith(
      '/api/capture/uav/resume?mission_id=resume_recovery',
      expect.objectContaining({ method: 'POST' }),
    );
  });

  it('does not send a stop request for a presumed-running child', async () => {
    vi.mocked(globalThis.fetch).mockImplementation(() => jsonResponse(captureStatus({
      missionId: 'uncertain_gps',
      uav: { service: 'presumed_running', file: 'recording', phase: 'reconciling' },
    })));

    await openTelemetry();

    const stop = await screen.findByRole('button', { name: '停止 GPS 採樣' });
    expect(stop).toBeDisabled();
    expect(stop).toHaveAttribute('aria-describedby');
    expect(globalThis.fetch).not.toHaveBeenCalledWith(
      '/api/capture/uav/stop?mission_id=uncertain_gps',
      expect.anything(),
    );
  });

  it('shows completed-with-warning child context', async () => {
    vi.mocked(globalThis.fetch).mockImplementation(() => jsonResponse(captureStatus({
      missionId: 'bound_warning',
      bind: true,
      overall: 'completed_with_warning',
      uav: { service: 'stopped', file: 'ready' },
      usrp: { service: 'failed', file: 'failed' },
    })));

    await openTelemetry();

    expect(await screen.findByText('已完成（有注意事項）')).toBeInTheDocument();
    expect(screen.getByText('Noise 失敗')).toBeInTheDocument();
  });

  it('shows a failed GPS reason for completed-with-warning missions', async () => {
    vi.mocked(globalThis.fetch).mockImplementation(() => jsonResponse(captureStatus({
      missionId: 'bound_gps_warning',
      bind: true,
      overall: 'completed_with_warning',
      uav: { service: 'failed', file: 'ready' },
      usrp: { service: 'stopped', file: 'uploaded' },
    })));

    await openTelemetry();

    expect(await screen.findByText('已完成（有注意事項）')).toBeInTheDocument();
    expect(screen.getByText('GPS 失敗')).toBeInTheDocument();
  });

  it('normalizes unknown child contract values safely', async () => {
    vi.mocked(globalThis.fetch).mockImplementation(() => jsonResponse(captureStatus({
      missionId: 'unknown_child',
      overall: 'future_state',
      uav: { connection: 'future', service: 'future', file: 'future', phase: 'future' },
    })));

    await openTelemetry();

    expect((await screen.findAllByText('未知')).length).toBeGreaterThan(0);
    const gps = screen.getByText('無人機 GPS 採樣').closest('section');
    expect(gps).not.toBeNull();
    expect(within(gps as HTMLElement).getAllByText('未知')).toHaveLength(4);
    expect(screen.getByRole('button', { name: '開始 GPS 採樣' })).toBeDisabled();
  });

  it('keeps legacy children without phase idle and operable', async () => {
    const payload = captureStatus({ missionId: 'legacy_child' });
    delete (payload.uav as Partial<typeof payload.uav>).phase;
    vi.mocked(globalThis.fetch).mockImplementation(() => jsonResponse(payload));

    await openTelemetry();

    await screen.findByText('任務：legacy_child');
    const gps = screen.getByText('無人機 GPS 採樣').closest('section');
    expect(gps).not.toBeNull();
    expect(within(gps as HTMLElement).getByText('階段').nextElementSibling).toHaveTextContent('閒置');
    expect(screen.getByRole('button', { name: '開始 GPS 採樣' })).toBeEnabled();
  });

  it('shows unknown for missing or unsupported overall states', async () => {
    vi.mocked(globalThis.fetch).mockImplementation(() => jsonResponse({
      ...captureStatus({ missionId: 'future_state' }),
      overall_state: 'future_state',
    }));

    await openTelemetry();

    expect(await screen.findByText('未知')).toBeInTheDocument();
    expect(screen.queryByText(/任務：future_state · 就緒/i)).not.toBeInTheDocument();
  });

  it('does not default a missing overall state to ready', async () => {
    const payload = captureStatus({ missionId: 'missing_state' });
    delete (payload as Partial<typeof payload>).overall_state;
    vi.mocked(globalThis.fetch).mockImplementation(() => jsonResponse(payload));

    await openTelemetry();

    expect(await screen.findByText('未知')).toBeInTheDocument();
  });

  it('restores active Bound missions with one common stop control', async () => {
    vi.mocked(globalThis.fetch).mockImplementation(() => jsonResponse(captureStatus({
      missionId: 'bound_1',
      bind: true,
      overall: 'running',
      uav: { service: 'running', file: 'recording' },
      usrp: { service: 'running', file: 'recording' },
    })));

    await openTelemetry();

    expect(await screen.findByRole('button', { name: '綁定任務模式' }))
      .toHaveAttribute('aria-pressed', 'true');
    expect(screen.queryByRole('button', { name: '停止 GPS 採樣' })).toBeNull();
    expect(screen.queryByRole('button', { name: '停止 Noise 採樣' })).toBeNull();
    expect(screen.queryByRole('button', { name: '測試模式' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'USRP 模式' })).toBeNull();
    expect(screen.getByRole('button', { name: '停止綁定任務' })).toBeEnabled();
  });

  it('keeps common Bound stop consumed after restoring a mission', async () => {
    vi.mocked(globalThis.fetch).mockImplementation(() => jsonResponse(captureStatus({
      missionId: 'bound_stopping',
      bind: true,
      overall: 'stopping',
      stopRequestedAt: '2026-08-12T00:00:00Z',
      uav: { service: 'presumed_running', file: 'finalizing', phase: 'stop_failed' },
      usrp: { service: 'stopping', file: 'finalizing', phase: 'stopping' },
    })));

    await openTelemetry();

    expect(await screen.findByRole('button', { name: '停止綁定任務' })).toBeDisabled();
  });

  it('offers Retry Stop only for the failed child and hides a stopped sibling action', async () => {
    const status = captureStatus({
      missionId: 'retry_child',
      bind: true,
      overall: 'stopping',
      stopRequestedAt: '2026-08-12T00:00:00Z',
      uav: { service: 'presumed_running', file: 'finalizing', phase: 'stop_failed', error: 'AP3 timeout' },
      usrp: { service: 'stopped', file: 'uploaded', phase: 'completed' },
    });
    vi.mocked(globalThis.fetch).mockImplementation((input) => {
      if (String(input).includes('/api/capture/uav/retry-stop')) {
        return jsonResponse({ ...status, uav: { ...status.uav, service: 'stopped', phase: 'stopped' } });
      }
      return jsonResponse(status);
    });
    const user = await openTelemetry();

    await screen.findByRole('button', { name: '重試停止 GPS 採樣' });
    const gps = screen.getByText('無人機 GPS 採樣').closest('section') as HTMLElement;
    const noise = screen.getByText('Noise 採樣').closest('section') as HTMLElement;
    expect(within(gps).getByRole('button', { name: '重試停止 GPS 採樣' })).toBeEnabled();
    expect(within(noise).queryByRole('button', { name: /停止 Noise 採樣/ })).toBeNull();

    await user.click(within(gps).getByRole('button', { name: '重試停止 GPS 採樣' }));
    expect(globalThis.fetch).toHaveBeenCalledWith(
      '/api/capture/uav/retry-stop?mission_id=retry_child',
      expect.objectContaining({ method: 'POST' }),
    );
  });

  it('renders a clean idle projection while retaining per-service mission history', async () => {
    const status = captureStatus({
      missionId: 'terminal_old_12345',
      overall: 'completed',
      uav: { service: 'stopped', file: 'ready', phase: 'completed', error: 'old terminal error' },
      usrp: { service: 'failed', file: 'failed', phase: 'failed' },
    }) as ReturnType<typeof captureStatus> & {
      control_mode: 'independent';
      active: null;
      history: { gps: { started_at: string; mission_id: string }; noise: null };
    };
    status.control_mode = 'independent';
    status.active = null;
    status.history = {
      gps: { started_at: '2026-08-13T16:00:00Z', mission_id: 'terminal_old_12345' },
      noise: null,
    };
    vi.mocked(globalThis.fetch).mockImplementation(() => jsonResponse(status));

    await openTelemetry();

    const gps = await screen.findByText('無人機 GPS 採樣');
    const gpsSection = gps.closest('section') as HTMLElement;
    expect(within(gpsSection).getAllByText('閒置').length).toBeGreaterThanOrEqual(2);
    expect(within(gpsSection).getByText('無檔案')).toBeInTheDocument();
    expect(within(gpsSection).getByLabelText('無人機 GPS 採樣 上次任務'))
      .toHaveTextContent('08/14 00:00:00 #12345');
    const noise = screen.getByText('Noise 採樣').closest('section') as HTMLElement;
    expect(within(noise).getByLabelText('Noise 採樣 上次任務')).toHaveTextContent('—');
    expect(screen.queryByText('old terminal error')).toBeNull();
    expect(screen.getByRole('button', { name: '綁定任務模式' }))
      .toHaveAttribute('aria-pressed', 'false');
  });

  it('restores the active projection instead of terminal compatibility fields', async () => {
    const terminal = captureStatus({
      missionId: 'old_terminal',
      overall: 'completed',
      uav: { service: 'stopped', file: 'ready', phase: 'completed' },
    });
    const active = captureStatus({
      missionId: 'bound_active',
      bind: true,
      overall: 'running',
      uav: { service: 'running', file: 'recording', phase: 'recording' },
      usrp: { service: 'running', file: 'recording', phase: 'recording' },
    });
    const payload = {
      ...terminal,
      control_mode: 'bound' as const,
      active,
      history: {
        gps: { started_at: '2026-08-13T17:00:00Z', mission_id: 'bound_active' },
        noise: { started_at: '2026-08-13T17:00:00Z', mission_id: 'bound_active' },
      },
    };
    vi.mocked(globalThis.fetch).mockImplementation(() => jsonResponse(payload));

    await openTelemetry();

    expect(await screen.findByRole('button', { name: '綁定任務模式' }))
      .toHaveAttribute('aria-pressed', 'true');
    expect(screen.getAllByText('錄製中').length).toBeGreaterThanOrEqual(2);
    expect(screen.queryByText('已停止')).not.toBeInTheDocument();
    expect(screen.getAllByText(/08\/14 01:00:00 #ctive/).length).toBe(2);
  });

  it('restores concurrent independent GPS and Noise captures after reload', async () => {
    const active = captureStatus({
      overall: 'running',
      uav: { service: 'running', file: 'recording', phase: 'recording' },
      usrp: { service: 'running', file: 'recording', phase: 'recording' },
    });
    active.mission_id = '';
    active.uav.mission_id = 'gps_active';
    active.usrp.mission_id = 'noise_active';
    const payload = {
      ...captureStatus(),
      control_mode: 'independent' as const,
      active,
      history: {
        gps: { started_at: '2026-08-13T17:00:00Z', mission_id: 'gps_active' },
        noise: { started_at: '2026-08-13T17:01:00Z', mission_id: 'noise_active' },
      },
    };
    vi.mocked(globalThis.fetch).mockImplementation(() => jsonResponse(payload));

    await openTelemetry();

    expect(await screen.findByRole('button', { name: '綁定任務模式' }))
      .toHaveAttribute('aria-pressed', 'false');
    expect(screen.getAllByText('錄製中').length).toBeGreaterThanOrEqual(2);
    expect(screen.getByRole('button', { name: '停止 GPS 採樣' })).toBeEnabled();
    expect(screen.getByRole('button', { name: '停止 Noise 採樣' })).toBeEnabled();
  });

  it('formats mission and health timestamps in Asia/Taipei', () => {
    expect(formatTaipeiTime('2026-08-13T16:00:00Z')).toBe('08/14 00:00:00');
    expect(formatTaipeiTime('2026-08-13T16:00:00')).toBe('08/13 16:00:00');
    expect(formatTaipeiTime('bad timestamp')).toBe('—');
  });

  it('labels the last sample according to its child domain', async () => {
    vi.mocked(globalThis.fetch).mockImplementation(() => jsonResponse(captureStatus({
      usrp: { last_sample_at: '2026-08-13T16:00:00Z' },
    })));

    const user = await openTelemetry();

    const noise = screen.getByText('Noise 採樣').closest('section') as HTMLElement;
    await user.click(within(noise).getByText('歷史任務與詳細進度'));
    expect(within(noise).getByText('最後 Noise')).toBeInTheDocument();
    expect(within(noise).queryByText('最後 GPS')).toBeNull();
  });

  it('clears a child operation error after a successful status refresh', async () => {
    vi.mocked(globalThis.fetch).mockImplementation((input) => {
      const url = String(input);
      if (url.includes('/api/capture/uav/start')) return jsonResponse({ detail: 'AP3 unavailable' }, false);
      return jsonResponse(captureStatus());
    });
    const user = await openTelemetry();

    await user.click(await screen.findByRole('button', { name: '開始 GPS 採樣' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('AP3 unavailable');

    await user.click(screen.getByRole('button', { name: '重新整理狀態' }));
    await waitFor(() => expect(screen.queryByText('AP3 unavailable')).toBeNull());
  });

  it('disables USRP Retry Stop while Raspberry Pi is offline and enables it after recovery', async () => {
    const offline = captureStatus({
      missionId: 'retry_usrp',
      bind: true,
      overall: 'stopping',
      stopRequestedAt: '2026-08-12T00:00:00Z',
      usrp: { connection: 'offline', service: 'presumed_running', file: 'finalizing', phase: 'stop_failed' },
    });
    offline.device_health.raspi.state = 'offline';
    offline.device_health.raspi.error = 'SSH timeout';
    const recovered = { ...offline, device_health: {
      ...offline.device_health,
      raspi: { ...offline.device_health.raspi, state: 'ready', error: '' },
    } };
    let healthCalls = 0;
    vi.mocked(globalThis.fetch).mockImplementation((input) => {
      if (String(input).includes('/api/capture/health')) {
        healthCalls += 1;
        return jsonResponse(healthCalls === 1 ? offline : recovered);
      }
      return jsonResponse(healthCalls === 0 ? offline : recovered);
    });
    vi.useFakeTimers();
    render(<USRPTelemetry />);
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    const noise = screen.getByText('Noise 採樣').closest('section') as HTMLElement;
    expect(within(noise).getByRole('button', { name: '重試停止 Noise 採樣' })).toBeDisabled();
    expect(within(noise).getByText(/請先重新連線 Raspberry Pi/)).toBeInTheDocument();

    await act(async () => { await vi.advanceTimersByTimeAsync(10000); });
    expect(within(noise).getByRole('button', { name: '重試停止 Noise 採樣' })).toBeEnabled();
    vi.useRealTimers();
  });

  it('stops independent jobs with each child mission id', async () => {
    const status = captureStatus({
      usrp: { service: 'running', file: 'recording' },
      uav: { service: 'running', file: 'recording' },
    });
    status.mission_id = '';
    status.uav.mission_id = 'gps_job';
    status.usrp.mission_id = 'noise_job';
    vi.mocked(globalThis.fetch).mockImplementation(() => jsonResponse(status));
    const user = await openTelemetry();

    await user.click(await screen.findByRole('button', { name: '停止 GPS 採樣' }));
    await user.click(screen.getByRole('button', { name: '停止 Noise 採樣' }));

    expect(globalThis.fetch).toHaveBeenCalledWith(
      '/api/capture/uav/stop?mission_id=gps_job',
      expect.objectContaining({ method: 'POST' }),
    );
    expect(globalThis.fetch).toHaveBeenCalledWith(
      '/api/capture/usrp/stop?mission_id=noise_job',
      expect.objectContaining({ method: 'POST' }),
    );
  });

  it('renders independent current phases for bound children', async () => {
    vi.mocked(globalThis.fetch).mockImplementation(() => jsonResponse(captureStatus({
      missionId: 'bound_phases',
      bind: true,
      overall: 'finalizing',
      uav: { service: 'stopping', file: 'finalizing', phase: 'finalizing_file' },
      usrp: { service: 'stopped', file: 'upload_pending', phase: 'upload_pending' },
    })));

    await openTelemetry();

    const uavProgress = await screen.findByLabelText('無人機 GPS 採樣 進度');
    const usrpProgress = screen.getByLabelText('Noise 採樣 進度');
    expect(within(uavProgress).getByText(/收尾 — 進行中/)).toBeInTheDocument();
    expect(within(usrpProgress).getByText(/收尾與上傳 — 進行中/)).toBeInTheDocument();
    expect(within(usrpProgress).getByText(/連線與設定 — 已完成/)).toBeInTheDocument();
  });

  it('retries a saved USRP upload without restarting capture', async () => {
    vi.mocked(globalThis.fetch).mockImplementation((input) => jsonResponse(captureStatus({
      missionId: 'noise_pending',
      overall: 'finalizing',
      usrp: {
        service: 'stopped',
        file: String(input).includes('/upload/retry') ? 'uploaded' : 'upload_pending',
        phase: String(input).includes('/upload/retry') ? 'completed' : 'upload_pending',
      },
    })));
    const user = await openTelemetry();

    await user.click(await screen.findByRole('button', { name: '重試上傳' }));

    expect(globalThis.fetch).toHaveBeenCalledWith(
      '/api/capture/usrp/upload/retry?mission_id=noise_pending',
      expect.objectContaining({ method: 'POST' }),
    );
  });

  it('shows reconciliation and child failures accessibly', async () => {
    vi.mocked(globalThis.fetch).mockImplementation(() => jsonResponse(captureStatus({
      missionId: 'noise_uncertain',
      usrp: {
        connection: 'offline',
        service: 'presumed_running',
        file: 'finalizing',
        phase: 'reconciling',
        error: 'remote command timed out',
      },
    })));

    await openTelemetry();

    expect(await screen.findByText('目前推定仍在執行，請先同步狀態再停止。')).toBeInTheDocument();
    expect(screen.getByRole('alert')).toHaveTextContent('remote command timed out');
    expect(screen.getByRole('button', { name: '停止 Noise 採樣' })).toBeDisabled();
  });

  it('shows plain text start failures without a JSON parse error', async () => {
    vi.mocked(globalThis.fetch).mockImplementation((input) => {
      if (String(input).includes('/api/capture/usrp/start')) {
        return textResponse('Internal Server Error');
      }
      return jsonResponse(captureStatus());
    });
    const user = await openTelemetry();

    await user.click(await screen.findByRole('button', { name: '開始 Noise 採樣' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('Internal Server Error');
    expect(screen.queryByText(/Unexpected token/)).not.toBeInTheDocument();
  });

  it('shows elapsed Manual Retry progress while the upload job is running', async () => {
    vi.mocked(globalThis.fetch).mockImplementation(() => jsonResponse(captureStatus({
      missionId: 'noise_manual_retry',
      overall: 'finalizing',
      usrp: {
        service: 'stopped', file: 'upload_pending', phase: 'upload_pending',
        upload_state: 'running', upload_mode: 'manual',
        upload_started_at: new Date(Date.now() - 3000).toISOString(),
      },
    })));

    await openTelemetry();

    expect(await screen.findByText(/手動重試 \(\d+ s\)/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '重試上傳' })).toBeDisabled();
  });

  it('shows persisted automatic retry countdown and updates it each second', async () => {
    vi.useFakeTimers();
    const base = new Date('2026-08-13T00:00:00.000Z');
    vi.setSystemTime(base);
    const next = new Date(base.getTime() + 5000).toISOString();
    vi.mocked(globalThis.fetch).mockImplementation(() => jsonResponse(captureStatus({
      missionId: 'noise_auto_wait',
      overall: 'finalizing',
      usrp: {
        service: 'stopped', file: 'upload_pending', phase: 'upload_pending',
        upload_retry_mode: 'automatic', upload_retry_state: 'waiting',
        upload_retry_attempt: 1, upload_retry_max_attempts: 3,
        upload_retry_next_attempt_at: next,
      },
    })));

    render(<USRPTelemetry />);
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(screen.getByText(/自動重試 1\/3 \(5 s\)/)).toBeInTheDocument();
    await act(async () => {
      vi.advanceTimersByTime(1000);
    });
    expect(screen.getByText(/自動重試 1\/3 \(4 s\)/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '重試上傳' })).not.toBeInTheDocument();
  });

  it('shows automatic retry elapsed text and exhaustion without a transient error', async () => {
    const started = new Date(Date.now() - 3000).toISOString();
    vi.mocked(globalThis.fetch).mockImplementationOnce(() => jsonResponse(captureStatus({
      missionId: 'noise_auto_running',
      overall: 'finalizing',
      usrp: {
        service: 'stopped', file: 'upload_pending', phase: 'upload_pending',
        upload_state: 'running', upload_mode: 'automatic', upload_started_at: started,
        upload_retry_mode: 'automatic', upload_retry_state: 'running',
        upload_retry_attempt: 2, upload_retry_max_attempts: 3,
      },
    })));
    const user = await openTelemetry();
    expect(await screen.findByText(/正在重試 2\/3 \(\d+ s\)/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '重試上傳' })).not.toBeInTheDocument();

    vi.mocked(globalThis.fetch).mockImplementation(() => jsonResponse(captureStatus({
      missionId: 'noise_auto_done',
      overall: 'finalizing',
      usrp: {
        service: 'stopped', file: 'upload_pending', phase: 'upload_pending',
        upload_retry_mode: 'automatic', upload_retry_state: 'exhausted',
        upload_retry_attempt: 3, upload_retry_max_attempts: 3,
      },
    })));
    await user.click(screen.getByRole('button', { name: '重新整理狀態' }));
    expect(await screen.findByText('自動重試已用盡')).toBeInTheDocument();
  });

  it('announces structured per-device Bound Start preflight errors', async () => {
    vi.mocked(globalThis.fetch).mockImplementation((input) => {
      if (String(input).includes('/api/capture/bind/start')) {
        return jsonResponse({
          detail: {
            errors: { ap3: 'USB disconnected', raspi: 'SSH timeout' },
          },
        }, false);
      }
      return jsonResponse(captureStatus());
    });
    const user = await openTelemetry();

    await user.click(await screen.findByRole('button', { name: '綁定任務模式' }));
    await user.click(screen.getByRole('button', { name: '開始綁定任務' }));

    const alerts = await screen.findAllByRole('alert');
    expect(alerts.map(alert => alert.textContent)).toEqual(expect.arrayContaining([
      'AP3: USB disconnected',
      'Raspberry Pi: SSH timeout',
    ]));
  });

  it('names AP3 when only AP3 Bound Start preflight fails', async () => {
    vi.mocked(globalThis.fetch).mockImplementation((input) => {
      if (String(input).includes('/api/capture/bind/start')) {
        return jsonResponse({ detail: { errors: { ap3: 'Forwarding unavailable' } } }, false);
      }
      return jsonResponse(captureStatus());
    });
    const user = await openTelemetry();

    await user.click(await screen.findByRole('button', { name: '綁定任務模式' }));
    await user.click(screen.getByRole('button', { name: '開始綁定任務' }));

    const alerts = await screen.findAllByRole('alert');
    expect(alerts.map(alert => alert.textContent)).toContain('AP3: Forwarding unavailable');
    expect(alerts.map(alert => alert.textContent).join(' ')).not.toContain('Raspberry Pi');
  });

  it('keeps only common controls while a Bound child is finalizing or upload is pending', async () => {
    vi.mocked(globalThis.fetch).mockImplementation(() => jsonResponse(captureStatus({
      missionId: 'pending-bound',
      bind: true,
      overall: 'finalizing',
      uav: { service: 'stopped', file: 'ready', phase: 'completed' },
      usrp: { service: 'stopped', file: 'upload_pending', phase: 'upload_pending' },
    })));

    await openTelemetry();

    expect(await screen.findByRole('button', { name: '綁定任務模式' })).toBeEnabled();
    expect(screen.queryByRole('button', { name: '測試模式' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'USRP 模式' })).toBeNull();
    expect(screen.getByRole('button', { name: '開始綁定任務' })).toBeDisabled();
  });

  it('polls active status single-flight after settle and stops on unmount', async () => {
    vi.useFakeTimers();
    const active = captureStatus({
      missionId: 'polling_mission',
      bind: true,
      overall: 'running',
      uav: { service: 'running', file: 'recording', phase: 'recording' },
      usrp: { service: 'running', file: 'recording', phase: 'recording' },
    });
    let statusCalls = 0;
    let resolvePending: ((response: Response) => void) | null = null;
    vi.mocked(globalThis.fetch).mockImplementation((input) => {
      if (!String(input).includes('/api/capture/status')) return jsonResponse(active);
      statusCalls += 1;
      if (statusCalls === 1) return jsonResponse(active);
      return new Promise<Response>((resolve) => { resolvePending = resolve; });
    });

    const view = render(<USRPTelemetry />);
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(statusCalls).toBe(1);

    await act(async () => { await vi.advanceTimersByTimeAsync(1999); });
    expect(statusCalls).toBe(1);
    await act(async () => { await vi.advanceTimersByTimeAsync(1); });
    expect(statusCalls).toBe(2);

    await act(async () => { await vi.advanceTimersByTimeAsync(10000); });
    expect(statusCalls).toBe(2);

    resolvePending?.(await jsonResponse(active));
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    await act(async () => { await vi.advanceTimersByTimeAsync(1999); });
    expect(statusCalls).toBe(2);

    view.unmount();
    await act(async () => { await vi.advanceTimersByTimeAsync(2000); });
    expect(statusCalls).toBe(2);
    vi.useRealTimers();
  });

  it('continues the next polling round after an aborted request', async () => {
    vi.useFakeTimers();
    const active = captureStatus({
      missionId: 'polling_timeout',
      overall: 'running',
      uav: { service: 'running', file: 'recording', phase: 'recording' },
      usrp: { service: 'running', file: 'recording', phase: 'recording' },
    });
    let statusCalls = 0;
    vi.mocked(globalThis.fetch).mockImplementation((input, init) => {
      if (!String(input).includes('/api/capture/status')) return jsonResponse(active);
      statusCalls += 1;
      if (statusCalls !== 2) return jsonResponse(active);
      return new Promise<Response>((_resolve, reject) => {
        init?.signal?.addEventListener('abort', () => {
          const error = new Error('aborted');
          error.name = 'AbortError';
          reject(error);
        });
      });
    });

    const view = render(<USRPTelemetry />);
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    await act(async () => { await vi.advanceTimersByTimeAsync(2000); });
    expect(statusCalls).toBe(2);
    await act(async () => { await vi.advanceTimersByTimeAsync(24999); });
    expect(statusCalls).toBe(2);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
      await Promise.resolve();
      await Promise.resolve();
    });
    await act(async () => { await vi.advanceTimersByTimeAsync(2000); });
    expect(statusCalls).toBe(3);

    view.unmount();
    vi.useRealTimers();
  });

  it('shares an in-flight status request and aborts it on unmount', async () => {
    const active = captureStatus({
      missionId: 'polling_unmount',
      overall: 'running',
      uav: { service: 'running', file: 'recording', phase: 'recording' },
      usrp: { service: 'running', file: 'recording', phase: 'recording' },
    });
    let statusCalls = 0;
    let pendingSignal: AbortSignal | null = null;
    vi.mocked(globalThis.fetch).mockImplementation((input, init) => {
      if (!String(input).includes('/api/capture/status')) return jsonResponse(active);
      statusCalls += 1;
      pendingSignal = init?.signal ?? null;
      return new Promise<Response>((_resolve, reject) => {
        init?.signal?.addEventListener('abort', () => {
          const error = new Error('aborted');
          error.name = 'AbortError';
          reject(error);
        });
      });
    });

    const view = render(<USRPTelemetry />);
    await act(async () => { await Promise.resolve(); });
    await userEvent.setup().click(screen.getByRole('button', { name: '重新整理狀態' }));
    expect(statusCalls).toBe(1);

    view.unmount();
    expect(pendingSignal?.aborted).toBe(true);
  });

  it('renders Ticket 02 control mode segment switcher, Chinese actions, and grouped progress', async () => {
    const user = userEvent.setup();
    render(<USRPTelemetry />);

    expect(await screen.findByRole('button', { name: '獨立採樣模式' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('button', { name: '綁定任務模式' })).toHaveAttribute('aria-pressed', 'false');
    expect(screen.getByText('裝置就緒')).toBeInTheDocument();
    expect(screen.getByText('任務狀態')).toBeInTheDocument();
    expect(screen.getByText('無人機 GPS 採樣')).toBeInTheDocument();
    expect(screen.getByText('Noise 採樣')).toBeInTheDocument();

    // Chinese buttons
    expect(screen.getByText('開始 GPS 採樣')).toBeInTheDocument();
    expect(screen.getByText('開始 Noise 採樣')).toBeInTheDocument();
    expect(screen.getByText('重新整理狀態')).toBeInTheDocument();

    // Grouped progress steps
    const uavProgress = screen.getByLabelText('無人機 GPS 採樣 進度');
    const usrpProgress = screen.getByLabelText('Noise 採樣 進度');
    expect(within(uavProgress).getByText(/準備 —/)).toBeInTheDocument();
    expect(within(uavProgress).getByText(/錄製 —/)).toBeInTheDocument();
    expect(within(uavProgress).getByText(/收尾 —/)).toBeInTheDocument();
    expect(within(usrpProgress).getByText(/連線與設定 —/)).toBeInTheDocument();
    expect(within(usrpProgress).getByText(/收尾與上傳 —/)).toBeInTheDocument();

    // Switch to Bound mode
    await user.click(screen.getByRole('button', { name: '綁定任務模式' }));
    expect(screen.getByRole('button', { name: '獨立採樣模式' })).toHaveAttribute('aria-pressed', 'false');
    expect(screen.getByRole('button', { name: '綁定任務模式' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByText('開始綁定任務')).toBeInTheDocument();
    expect(screen.getByText('停止綁定任務')).toBeInTheDocument();
  });

  it('uses Chinese accessible labels and explains an unavailable AP3 blocker', async () => {
    const status = captureStatus();
    status.device_health.ap3.state = 'offline';
    vi.mocked(globalThis.fetch).mockImplementation(() => jsonResponse(status));

    render(<USRPTelemetry />);

    expect(await screen.findByRole('button', { name: '綁定任務模式' })).toBeInTheDocument();
    const start = screen.getByRole('button', { name: '開始 GPS 採樣' });
    expect(start).toBeDisabled();
    expect(screen.getByText('AP3 尚未就緒。')).toBeInTheDocument();
  });
});
