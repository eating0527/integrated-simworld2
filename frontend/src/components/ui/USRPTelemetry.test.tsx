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

describe('USRPTelemetry Raspberry Pi control', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn(() => samplingResponse({
      success: true,
      raspi_connected: true,
      session_connected: true,
      service_state: 'stopped',
      message: 'drone.service stopped',
      service_messages: ['Active: inactive'],
    })));
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it('checks Raspberry Pi and service status when the panel loads', async () => {
    render(<USRPTelemetry event={null} />);

    await waitFor(() => expect(globalThis.fetch).toHaveBeenCalledWith('/api/usrp/sampling/status'));
    expect(await screen.findByText('已連線')).toBeInTheDocument();
    expect(screen.getByText('已停止')).toBeInTheDocument();
    expect(screen.getByText('drone.service stopped')).toBeInTheDocument();
    expect(screen.getByText('Active: inactive')).toBeInTheDocument();
  });

  it('connects and disconnects Raspberry Pi through explicit controls', async () => {
    vi.mocked(globalThis.fetch)
      .mockImplementationOnce(() => samplingResponse({
        success: false,
        raspi_connected: false,
        session_connected: false,
        service_state: 'unknown',
        message: '尚未連線',
        service_messages: [],
      }))
      .mockImplementationOnce(() => samplingResponse({
        success: true,
        raspi_connected: true,
        session_connected: true,
        service_state: 'stopped',
        message: 'RasPi connected',
        service_messages: ['Active: inactive'],
      }))
      .mockImplementationOnce(() => samplingResponse({
        success: true,
        raspi_connected: false,
        session_connected: false,
        service_state: 'unknown',
        message: 'RasPi disconnected',
        service_messages: [],
      }));
    const user = userEvent.setup();

    render(<USRPTelemetry event={null} />);

    expect(await screen.findByText('未連線')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '連線' }));
    await waitFor(() => expect(globalThis.fetch).toHaveBeenCalledWith('/api/usrp/sampling/connect', { method: 'POST' }));
    expect(await screen.findByText('RasPi connected')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: '中斷' }));
    await waitFor(() => expect(globalThis.fetch).toHaveBeenCalledWith('/api/usrp/sampling/disconnect', { method: 'POST' }));
    expect(await screen.findByText('RasPi disconnected')).toBeInTheDocument();
  });

  it('disables start when Raspberry Pi is not connected and shows failures', async () => {
    vi.mocked(globalThis.fetch).mockImplementation(() => samplingResponse({
      success: false,
      raspi_connected: false,
      session_connected: false,
      service_state: 'unknown',
      message: 'SSH timeout',
      service_messages: [],
    }, false));

    render(<USRPTelemetry event={null} />);

    expect(await screen.findByText('未連線')).toBeInTheDocument();
    expect(screen.getByRole('alert')).toHaveTextContent('SSH timeout');
    expect(screen.getByRole('button', { name: '開始採樣' })).toBeDisabled();
  });

  it('starts, stops, and refreshes service messages through the backend API', async () => {
    vi.mocked(globalThis.fetch)
      .mockImplementationOnce(() => samplingResponse({
        success: true,
        raspi_connected: true,
        session_connected: true,
        service_state: 'stopped',
        message: 'drone.service stopped',
        service_messages: ['Active: inactive'],
      }))
      .mockImplementationOnce(() => samplingResponse({
        success: true,
        raspi_connected: true,
        session_connected: true,
        service_state: 'running',
        message: 'drone.service started',
        service_messages: ['Started sampler', 'Active: active (running)'],
      }))
      .mockImplementationOnce(() => samplingResponse({
        success: true,
        raspi_connected: true,
        session_connected: true,
        service_state: 'running',
        message: 'drone.service messages loaded',
        service_messages: ['Active: active (running)', 'Processing samples'],
      }))
      .mockImplementationOnce(() => samplingResponse({
        success: true,
        raspi_connected: true,
        session_connected: true,
        service_state: 'stopped',
        message: 'drone.service stopped',
        service_messages: ['Stopped sampler', 'Active: inactive'],
      }));
    const user = userEvent.setup();

    render(<USRPTelemetry event={null} />);

    await user.click(await screen.findByRole('button', { name: '開始採樣' }));
    await waitFor(() => expect(globalThis.fetch).toHaveBeenCalledWith('/api/usrp/sampling/start', { method: 'POST' }));
    expect(await screen.findByText('採樣中')).toBeInTheDocument();
    expect(screen.getByText('Started sampler')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: '更新訊息' }));
    await waitFor(() => expect(globalThis.fetch).toHaveBeenCalledWith('/api/usrp/sampling/messages'));
    expect(await screen.findByText('Processing samples')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: '終止採樣' }));
    await waitFor(() => expect(globalThis.fetch).toHaveBeenCalledWith('/api/usrp/sampling/stop', { method: 'POST' }));
    expect(await screen.findByText('已停止')).toBeInTheDocument();
    expect(screen.getByText('Stopped sampler')).toBeInTheDocument();
  });
});
