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
  last_attempt_at?: string;
  last_success_at?: string;
  refresh_state?: string;
  consecutive_failures?: number;
  next_retry_at?: string;
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
    expect(screen.getByRole('button', { name: 'Start GPS' })).toBeEnabled();
    expect(screen.getByRole('button', { name: 'Start USRP' })).toBeEnabled();
    expect(globalThis.fetch).toHaveBeenCalledWith(
      '/api/capture/status?usrp_mode=test',
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
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
    expect(screen.getByRole('button', { name: 'Start GPS' })).toBeDisabled();
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
    expect(screen.getByRole('button', { name: 'Stop GPS · Recording' })).toBeEnabled();
    expect(screen.getByRole('button', { name: 'Stop USRP · Recording' })).toBeEnabled();
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

    await user.click(await screen.findByRole('button', { name: 'Stop GPS · Recording' }));
    await user.click(await screen.findByRole('button', { name: 'Stop USRP · Recording' }));

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
      usrp: { service: 'stopped', file: 'upload_pending', phase: 'upload_pending' },
    })));
    await openTelemetry();
    expect((await screen.findAllByText(/CSV saved/)).length).toBeGreaterThan(0);
    expect(screen.queryByRole('button', { name: 'Retry upload' })).not.toBeInTheDocument();
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

  it('does not overlap delayed polling requests and uses a five second deadline', async () => {
    vi.useFakeTimers();
    let resolveFirst!: (value: Response) => void;
    const first = new Promise<Response>(resolve => { resolveFirst = resolve; });
    vi.mocked(globalThis.fetch).mockReturnValueOnce(first);
    render(<USRPTelemetry />);
    await vi.advanceTimersByTimeAsync(3000);
    expect(globalThis.fetch).toHaveBeenCalledTimes(1);
    expect(vi.mocked(globalThis.fetch).mock.calls[0][1]).toEqual(expect.objectContaining({ signal: expect.any(AbortSignal) }));
    resolveFirst((await jsonResponse(captureStatus())) as Response);
    await vi.advanceTimersByTimeAsync(0);
    await vi.advanceTimersByTimeAsync(3000);
    expect(globalThis.fetch).toHaveBeenCalledTimes(2);
    vi.useRealTimers();
  });

  it('aborts status requests when unmounted', async () => {
    let signal!: AbortSignal;
    vi.mocked(globalThis.fetch).mockImplementation((_input, init) => {
      signal = init?.signal as AbortSignal;
      return new Promise<Response>(() => {});
    });
    const view = render(<USRPTelemetry />);
    await waitFor(() => expect(signal).toBeDefined());
    view.unmount();
    expect(signal.aborted).toBe(true);
  });

  it('refreshes GPS and USRP through their reconciliation routes independently', async () => {
    const user = await openTelemetry();
    await user.click(await screen.findByRole('button', { name: 'Refresh GPS' }));
    await user.click(screen.getByRole('button', { name: 'Refresh USRP' }));
    expect(globalThis.fetch).toHaveBeenCalledWith('/api/capture/gps/refresh', expect.objectContaining({ method: 'POST' }));
    expect(globalThis.fetch).toHaveBeenCalledWith('/api/capture/usrp/refresh?mission_id=', expect.objectContaining({ method: 'POST' }));
  });

  it('Refresh all reconciles both devices using the snapshot mission id', async () => {
    vi.mocked(globalThis.fetch).mockImplementation(() => jsonResponse(captureStatus({ missionId: 'refresh_mission' })));
    const user = await openTelemetry();

    await user.click(await screen.findByRole('button', { name: 'Refresh all' }));

    await waitFor(() => {
      expect(globalThis.fetch).toHaveBeenCalledWith('/api/capture/gps/refresh', expect.objectContaining({ method: 'POST' }));
      expect(globalThis.fetch).toHaveBeenCalledWith('/api/capture/usrp/refresh?mission_id=refresh_mission', expect.objectContaining({ method: 'POST' }));
    });
  });

  it('renders persisted last seen and retry countdown for offline children', async () => {
    vi.mocked(globalThis.fetch).mockImplementation(() => jsonResponse(captureStatus({
      usrp: { connection: 'offline', service: 'presumed_running', file: 'ready', last_success_at: '2026-06-24T00:00:00Z', next_retry_at: new Date(Date.now() + 30000).toISOString() },
    })));
    await openTelemetry();
    expect(await screen.findByText('Offline')).toBeInTheDocument();
    expect(screen.getByText(/Last seen/)).toBeInTheDocument();
    expect(screen.getByText(/Retry in/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Stop unconfirmed' })).toBeDisabled();
  });

  it('keeps GPS stop enabled while USRP refresh is pending', async () => {
    vi.mocked(globalThis.fetch).mockImplementation((input) => {
      if (String(input).includes('/api/capture/usrp/refresh')) return new Promise<Response>(() => {});
      return jsonResponse(captureStatus({ uav: { service: 'running', file: 'recording' }, usrp: { service: 'running', file: 'recording' } }));
    });
    const user = await openTelemetry();
    await user.click(await screen.findByRole('button', { name: 'Refresh USRP' }));
    expect(screen.getByRole('button', { name: 'Stop GPS · Recording' })).toBeEnabled();
  });

  it('uses dynamic capture labels and removes unsupported upload retry', async () => {
    vi.mocked(globalThis.fetch).mockImplementation(() => jsonResponse(captureStatus({
      usrp: { service: 'stopped', file: 'upload_pending' },
      uav: { service: 'starting' },
    })));
    await openTelemetry();
    expect(await screen.findByRole('button', { name: 'Starting GPS…' })).toBeDisabled();
    expect((await screen.findAllByText(/CSV saved/)).length).toBeGreaterThan(0);
    expect(screen.queryByRole('button', { name: 'Retry upload' })).not.toBeInTheDocument();
  });

  it('provides native details progress and reduced motion action styling', async () => {
    await openTelemetry();
    expect(await screen.findAllByRole('group')).not.toHaveLength(0);
    expect(document.querySelector('style')?.textContent).toMatch(/prefers-reduced-motion/);
    expect(document.querySelector('style')?.textContent).toMatch(/scale\(\.97\)/);
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
