import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { USRPTelemetry } from './USRPTelemetry';

function samplingResponse(payload: unknown, ok = true) {
  return Promise.resolve({
    ok,
    json: () => Promise.resolve(payload),
  } as Response);
}

function statusPayload(overrides: Record<string, unknown> = {}) {
  return {
    success: true,
    raspi_connected: true,
    session_connected: true,
    mode: 'test',
    service_name: 'drone_test.service',
    service_state: 'stopped',
    message: 'drone_test.service stopped',
    service_messages: ['Active: inactive'],
    ...overrides,
  };
}

describe('USRPTelemetry Raspberry Pi dual-mode control', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn(() => samplingResponse(statusPayload())));
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it('defaults to test mode and checks drone_test.service when the panel loads', async () => {
    render(<USRPTelemetry event={null} />);

    expect(screen.getAllByText('USRP 設定')).toHaveLength(1);
    await waitFor(() => expect(globalThis.fetch).toHaveBeenCalledWith('/api/usrp/sampling/status?mode=test'));
    expect(screen.getByRole('button', { name: '測試模式' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getAllByText('測試模式').length).toBeGreaterThan(0);
    expect(screen.getByText('drone_test.service')).toBeInTheDocument();
    expect(screen.getByText('已連線')).toBeInTheDocument();
    expect(screen.getByText('已停止')).toBeInTheDocument();
    expect(screen.getByText('drone_test.service stopped')).toBeInTheDocument();
  });

  it('switches to USRP mode and reloads drone.service status', async () => {
    vi.mocked(globalThis.fetch)
      .mockImplementationOnce(() => samplingResponse(statusPayload()))
      .mockImplementationOnce(() => samplingResponse(statusPayload({
        mode: 'usrp',
        service_name: 'drone.service',
        message: 'drone.service stopped',
      })));
    const user = userEvent.setup();

    render(<USRPTelemetry event={null} />);

    await user.click(await screen.findByRole('button', { name: 'USRP 模式' }));
    await waitFor(() => expect(globalThis.fetch).toHaveBeenCalledWith('/api/usrp/sampling/status?mode=usrp'));
    expect(screen.getByRole('button', { name: 'USRP 模式' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByText('drone.service')).toBeInTheDocument();
    expect(screen.getByText('drone.service stopped')).toBeInTheDocument();
  });

  it('sends the selected mode when starting, refreshing messages, and stopping', async () => {
    vi.mocked(globalThis.fetch)
      .mockImplementationOnce(() => samplingResponse(statusPayload()))
      .mockImplementationOnce(() => samplingResponse(statusPayload({
        service_state: 'running',
        message: 'drone_test.service started',
        service_messages: ['Started test sampler', 'Active: active (running)'],
      })))
      .mockImplementationOnce(() => samplingResponse(statusPayload({
        service_state: 'running',
        message: 'drone_test.service messages loaded',
        service_messages: ['Processing test samples'],
      })))
      .mockImplementationOnce(() => samplingResponse(statusPayload({
        service_state: 'stopped',
        message: 'drone_test.service stopped',
        service_messages: ['Stopped test sampler', 'Active: inactive'],
      })));
    const user = userEvent.setup();

    render(<USRPTelemetry event={null} />);

    await user.click(await screen.findByRole('button', { name: '開始採樣' }));
    await waitFor(() => expect(globalThis.fetch).toHaveBeenCalledWith('/api/usrp/sampling/start?mode=test', { method: 'POST' }));
    expect(await screen.findByText('採樣中')).toBeInTheDocument();
    expect(screen.getByText('Started test sampler')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: '更新訊息' }));
    await waitFor(() => expect(globalThis.fetch).toHaveBeenCalledWith('/api/usrp/sampling/messages?mode=test'));
    expect(await screen.findByText('Processing test samples')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: '終止採樣' }));
    await waitFor(() => expect(globalThis.fetch).toHaveBeenCalledWith('/api/usrp/sampling/stop?mode=test', { method: 'POST' }));
    expect(await screen.findByText('已停止')).toBeInTheDocument();
    expect(screen.getByText('Stopped test sampler')).toBeInTheDocument();
  });

  it('locks mode switching while sampling is running and unlocks it after stop', async () => {
    vi.mocked(globalThis.fetch)
      .mockImplementationOnce(() => samplingResponse(statusPayload()))
      .mockImplementationOnce(() => samplingResponse(statusPayload({
        service_state: 'running',
        message: 'drone_test.service started',
      })))
      .mockImplementationOnce(() => samplingResponse(statusPayload({
        service_state: 'stopped',
        message: 'drone_test.service stopped',
      })));
    const user = userEvent.setup();

    render(<USRPTelemetry event={null} />);

    await user.click(await screen.findByRole('button', { name: '開始採樣' }));
    expect(await screen.findByText('採樣中')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'USRP 模式' })).toBeDisabled();

    await user.click(screen.getByRole('button', { name: '終止採樣' }));
    expect(await screen.findByText('已停止')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'USRP 模式' })).not.toBeDisabled();
  });

  it('keeps start disabled when Raspberry Pi is not connected', async () => {
    vi.mocked(globalThis.fetch).mockImplementation(() => samplingResponse(statusPayload({
      success: false,
      raspi_connected: false,
      session_connected: false,
      service_state: 'unknown',
      message: 'SSH timeout',
      service_messages: [],
    }), false));

    render(<USRPTelemetry event={null} />);

    expect(await screen.findByText('未連線')).toBeInTheDocument();
    expect(screen.getByRole('alert')).toHaveTextContent('SSH timeout');
    expect(screen.getByRole('button', { name: '開始採樣' })).toBeDisabled();
  });
});
