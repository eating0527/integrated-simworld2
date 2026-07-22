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
