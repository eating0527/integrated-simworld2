import { afterEach, describe, expect, it } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { AircraftTelemetry } from './AircraftTelemetry';

describe('AircraftTelemetry', () => {
  afterEach(() => {
    cleanup();
  });

  it('shows the panel title once', () => {
    render(<AircraftTelemetry device={null} isTracked={false} />);

    expect(screen.getAllByText('無人機遙測')).toHaveLength(1);
  });

  it('shows an unidentified state and N/A without a device', () => {
    render(<AircraftTelemetry statusBar device={null} isTracked={false} />);

    const summary = screen.getByLabelText('GPS 狀態摘要');
    expect(summary).toHaveTextContent('未識別');
    expect(summary).toHaveTextContent('N/A');
    expect(summary.querySelector('.status-summary__state')).toHaveClass('status-summary__state--unidentified');
  });

  it('shows N/A when device coordinates are unavailable', () => {
    render(
      <AircraftTelemetry
        statusBar
        device={{
          lat: Number.NaN,
          lon: 121.7654321,
          alt: 88.4,
          accuracy: 2.5,
          deviceId: 'uav-1',
          deviceName: 'M4P TOP Aircraft',
          deviceType: 'uav',
          timestamp: 1,
          lastUpdateTime: Date.now(),
        }}
        isTracked={false}
      />,
    );

    expect(screen.getByLabelText('GPS 狀態摘要')).toHaveTextContent('已識別');
    expect(screen.getByLabelText('GPS 狀態摘要')).toHaveTextContent('N/A');
  });

  it('does not crash when a GPS payload omits accuracy', () => {
    render(
      <AircraftTelemetry
        device={{
          lat: 24.1234567,
          lon: 121.7654321,
          alt: 88.4,
          accuracy: undefined,
          deviceId: 'uav-1',
          deviceName: 'M4P TOP Aircraft',
          deviceType: 'uav',
          timestamp: 1,
          lastUpdateTime: Date.now(),
        } as unknown as import('@/hooks/useGPSSync').GPSDevice}
        isTracked={false}
      />,
    );

    expect(screen.getByText('Accuracy')).toBeInTheDocument();
    expect(screen.getByText('N/A')).toBeInTheDocument();
  });

  it('shows a collapsed coordinate summary and expands telemetry details', async () => {
    const user = userEvent.setup();
    render(
      <AircraftTelemetry
        statusBar
        deviceId="uav-1"
        device={{
          lat: 24.1234567,
          lon: 121.7654321,
          alt: 88.4,
          accuracy: 2.5,
          deviceId: 'uav-1',
          deviceName: 'M4P TOP Aircraft',
          deviceType: 'uav',
          timestamp: 1,
          lastUpdateTime: Date.now(),
        }}
        isTracked={false}
        onTrack={() => {}}
      />,
    );

    expect(screen.getByLabelText('GPS 狀態摘要')).toHaveTextContent('已識別');
    expect(screen.getByLabelText('GPS 狀態摘要').querySelector('.status-summary__state')).toHaveClass('status-summary__state');
    expect(screen.getByLabelText('GPS 狀態摘要')).toHaveTextContent('24.123');
    expect(screen.getByLabelText('GPS 狀態摘要')).toHaveTextContent('121.765');
    expect(screen.getByLabelText('GPS 狀態摘要')).toHaveTextContent('88.4');
    expect(screen.queryByRole('button', { name: 'Track' })).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /restore GPS 狀態/i }));

    expect(screen.getByRole('button', { name: 'Track' })).toBeInTheDocument();
  });
});
