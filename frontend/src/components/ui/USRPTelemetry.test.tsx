import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { USRPTelemetry } from './USRPTelemetry';

type ChildOverrides = {
  connection?: string;
  service?: string;
  file?: string;
  phase?: string;
  error?: string;
};

function captureStatus(options: {
  missionId?: string;
  bind?: boolean;
  mode?: 'test' | 'usrp';
  overall?: string;
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
    uav: child(options.uav),
    usrp: child(options.usrp),
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
    vi.unstubAllGlobals();
  });

  it('defaults Bind off and exposes independent UAV and USRP controls', async () => {
    render(<USRPTelemetry />);

    expect(screen.getByRole('button', { name: 'Minimize 採樣控制面板' }))
      .toHaveAttribute('aria-expanded', 'true');

    expect(await screen.findByText('無人機 GPS 採樣')).toBeInTheDocument();
    expect(screen.getByText('USRP 干擾採樣')).toBeInTheDocument();
    expect(screen.getByRole('switch', { name: 'Bind services' }))
      .toHaveAttribute('aria-checked', 'false');
    expect(screen.getByRole('button', { name: 'Start UAV' })).toBeEnabled();
    expect(screen.getByRole('button', { name: 'Start USRP' })).toBeEnabled();
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

    expect(await screen.findByLabelText('AP3 Device Health')).toHaveTextContent('Offline');
    expect(screen.getByLabelText('Raspberry Pi Device Health')).toHaveTextContent('Ready');
    expect(screen.getByText('USB disconnected')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Start UAV' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Start USRP' })).toBeEnabled();
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

    expect(await screen.findByLabelText('AP3 Device Health')).toHaveTextContent('Unknown');
    expect(screen.getByText('COMPLETED')).toBeInTheDocument();
    expect(screen.getByText('ap3 health result is stale')).toBeInTheDocument();
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

    await user.click(await screen.findByRole('button', { name: 'USRP mode' }));
    await user.click(screen.getByRole('button', { name: 'Start USRP' }));

    await waitFor(() => expect(globalThis.fetch).toHaveBeenCalledWith(
      '/api/capture/usrp/start',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ usrp_mode: 'usrp', scene: 'NTPU', map_type: 'iss' }),
      }),
    ));
  });

  it('uses a shared Bind start only when both services are ready', async () => {
    const user = await openTelemetry();

    await user.click(await screen.findByRole('switch', { name: 'Bind services' }));
    await user.click(screen.getByRole('button', { name: 'Start Bound Capture' }));

    await waitFor(() => expect(globalThis.fetch).toHaveBeenCalledWith(
      '/api/capture/bind/start',
      expect.objectContaining({ method: 'POST' }),
    ));
    expect(screen.getByRole('button', { name: 'Start UAV' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Start USRP' })).toBeDisabled();
  });

  it('locks Bind and mode switching while USRP is running', async () => {
    vi.mocked(globalThis.fetch).mockImplementation(() => jsonResponse(captureStatus({
      missionId: 'noise_2',
      mode: 'usrp',
      usrp: { service: 'running', file: 'recording' },
    })));

    await openTelemetry();

    expect(await screen.findByRole('switch', { name: 'Bind services' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Test mode' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'USRP mode' })).toBeDisabled();
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

    expect(await screen.findByText('Presumed running')).toBeInTheDocument();
    expect(screen.getByText('Pending upload')).toBeInTheDocument();
    expect(screen.queryByText('Completed')).not.toBeInTheDocument();
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

    expect(await screen.findByText('DEGRADED · GPS FAILED · NOISE RECORDING')).toBeInTheDocument();
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

    expect(await screen.findByText(/^DEGRADED · NOISE OFFLINE/)).toBeInTheDocument();
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

    expect(await screen.findByText('COMPLETED WITH WARNING · NOISE FAILED')).toBeInTheDocument();
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

    expect(await screen.findByText('COMPLETED WITH WARNING · GPS FAILED')).toBeInTheDocument();
  });

  it('normalizes unknown child contract values safely', async () => {
    vi.mocked(globalThis.fetch).mockImplementation(() => jsonResponse(captureStatus({
      missionId: 'unknown_child',
      overall: 'future_state',
      uav: { connection: 'future', service: 'future', file: 'future', phase: 'future' },
    })));

    await openTelemetry();

    expect(await screen.findByText('UNKNOWN')).toBeInTheDocument();
    const gps = screen.getByText('無人機 GPS 採樣').closest('section');
    expect(gps).not.toBeNull();
    expect(within(gps as HTMLElement).getAllByText('Unknown')).toHaveLength(4);
    expect(screen.getByRole('button', { name: 'Start UAV' })).toBeDisabled();
  });

  it('keeps legacy children without phase idle and operable', async () => {
    const payload = captureStatus({ missionId: 'legacy_child' });
    delete (payload.uav as Partial<typeof payload.uav>).phase;
    vi.mocked(globalThis.fetch).mockImplementation(() => jsonResponse(payload));

    await openTelemetry();

    await screen.findByText('Mission: legacy_child');
    const gps = screen.getByText('無人機 GPS 採樣').closest('section');
    expect(gps).not.toBeNull();
    expect(within(gps as HTMLElement).getByText('Phase').nextElementSibling).toHaveTextContent('Idle');
    expect(screen.getByRole('button', { name: 'Start UAV' })).toBeEnabled();
  });

  it('shows unknown for missing or unsupported overall states', async () => {
    vi.mocked(globalThis.fetch).mockImplementation(() => jsonResponse({
      ...captureStatus({ missionId: 'future_state' }),
      overall_state: 'future_state',
    }));

    await openTelemetry();

    expect(await screen.findByText('UNKNOWN')).toBeInTheDocument();
    expect(screen.queryByText(/Mission: future_state · ready/i)).not.toBeInTheDocument();
  });

  it('does not default a missing overall state to ready', async () => {
    const payload = captureStatus({ missionId: 'missing_state' });
    delete (payload as Partial<typeof payload>).overall_state;
    vi.mocked(globalThis.fetch).mockImplementation(() => jsonResponse(payload));

    await openTelemetry();

    expect(await screen.findByText('UNKNOWN')).toBeInTheDocument();
  });

  it('restores active Bind missions and offers individual stop plus Stop All', async () => {
    vi.mocked(globalThis.fetch).mockImplementation(() => jsonResponse(captureStatus({
      missionId: 'bound_1',
      bind: true,
      overall: 'running',
      uav: { service: 'running', file: 'recording' },
      usrp: { service: 'running', file: 'recording' },
    })));

    await openTelemetry();

    expect(await screen.findByRole('switch', { name: 'Bind services' }))
      .toHaveAttribute('aria-checked', 'true');
    expect(screen.getByRole('button', { name: 'Stop UAV' })).toBeEnabled();
    expect(screen.getByRole('button', { name: 'Stop USRP' })).toBeEnabled();
    expect(screen.getByRole('button', { name: 'Stop All' })).toBeEnabled();
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

    await user.click(await screen.findByRole('button', { name: 'Stop UAV' }));
    await user.click(screen.getByRole('button', { name: 'Stop USRP' }));

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

    const uavProgress = await screen.findByLabelText('無人機 GPS 採樣 progress');
    const usrpProgress = screen.getByLabelText('USRP 干擾採樣 progress');
    expect(within(uavProgress).getByText(/Finalize CSV — current/)).toBeInTheDocument();
    expect(within(usrpProgress).getByText(/Upload — current/)).toBeInTheDocument();
    expect(within(usrpProgress).getByText(/Connect — completed/)).toBeInTheDocument();
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

    await user.click(await screen.findByRole('button', { name: 'Retry upload' }));

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

    expect(await screen.findByText('Reconciling presumed-running state')).toHaveAttribute('aria-live', 'polite');
    expect(screen.getByRole('alert')).toHaveTextContent('remote command timed out');
    expect(screen.getByText(/reconcile status before stopping/i)).toBeInTheDocument();
  });

  it('shows plain text start failures without a JSON parse error', async () => {
    vi.mocked(globalThis.fetch).mockImplementation((input) => {
      if (String(input).includes('/api/capture/usrp/start')) {
        return textResponse('Internal Server Error');
      }
      return jsonResponse(captureStatus());
    });
    const user = await openTelemetry();

    await user.click(await screen.findByRole('button', { name: 'Start USRP' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('Internal Server Error');
    expect(screen.queryByText(/Unexpected token/)).not.toBeInTheDocument();
  });
});
