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

    expect(screen.getByLabelText('無人機遙測摘要')).toHaveTextContent('LAT 24.12346');
    expect(screen.getByLabelText('無人機遙測摘要')).toHaveTextContent('LON 121.76543');
    expect(screen.getByLabelText('無人機遙測摘要')).toHaveTextContent('ALT 88.4 m');
    expect(screen.queryByRole('button', { name: 'Track' })).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /restore 無人機遙測/i }));

    expect(screen.getByRole('button', { name: 'Track' })).toBeInTheDocument();
  });
});
