import { afterEach, describe, expect, it } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';

import { AircraftTelemetry } from './AircraftTelemetry';
import { GPSStatus } from './GPSStatus';

function renderPanel(statusBar = false) {
  render(
    <GPSStatus
      myDeviceId="device-123456"
      deviceName="Drone"
      onRenameClick={() => {}}
      allDevices={new Map(statusBar ? [[
        'uav-1',
        {
          lat: 24.1,
          lon: 121.2,
          alt: 80,
          accuracy: 2,
          deviceId: 'uav-1',
          deviceName: 'UAV 1',
          deviceType: 'uav' as const,
          timestamp: 1,
          lastUpdateTime: 1,
        },
      ]] : [])}
      uavPath={[]}
      onClearPath={() => {}}
      connectionStatus="connected"
      statusBar={statusBar}
    />,
  );
}

describe('GPSStatus', () => {
  afterEach(() => {
    cleanup();
  });

  it('shows the connection status panel title', () => {
    renderPanel();

    expect(screen.getByText('連線狀態')).toBeInTheDocument();
  });

  it('uses the shared minimizable panel shell', async () => {
    const user = userEvent.setup();

    renderPanel();

    await user.click(screen.getByRole('button', { name: /minimize/i }));

    expect(screen.queryByRole('button', { name: '改名' })).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /restore/i }));

    expect(screen.getByRole('button', { name: '改名' })).toBeInTheDocument();
  });

  it('shows connection light and device count in the collapsed status summary', async () => {
    const user = userEvent.setup();
    renderPanel(true);

    expect(screen.getByLabelText('連線狀態摘要')).toHaveTextContent('1 台');
    expect(screen.getByLabelText('連線狀態摘要')).not.toHaveTextContent('已連線');
    expect(screen.queryByRole('button', { name: '改名' })).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /restore 連線狀態/i }));

    expect(screen.getByRole('button', { name: '改名' })).toBeInTheDocument();
  });

  it('keeps GPS and connection status panels mutually exclusive', async () => {
    const user = userEvent.setup();

    function StatusPanels() {
      const [activePanel, setActivePanel] = useState<'gps' | 'connection' | null>(null);
      return (
        <>
          <AircraftTelemetry
            statusBar
            device={null}
            isTracked={false}
            minimized={activePanel !== 'gps'}
            onMinimizedChange={minimized => setActivePanel(minimized ? null : 'gps')}
          />
          <GPSStatus
            myDeviceId="device-123456"
            deviceName="Drone"
            onRenameClick={() => {}}
            allDevices={new Map()}
            uavPath={[]}
            onClearPath={() => {}}
            connectionStatus="connected"
            statusBar
            minimized={activePanel !== 'connection'}
            onMinimizedChange={minimized => setActivePanel(minimized ? null : 'connection')}
          />
        </>
      );
    }

    const { container } = render(<StatusPanels />);
    const titleButtons = container.querySelectorAll('.min-panel__title-btn');

    await user.click(titleButtons[0]);
    expect(titleButtons[0]).toHaveAttribute('aria-expanded', 'true');
    expect(titleButtons[1]).toHaveAttribute('aria-expanded', 'false');

    await user.click(titleButtons[1]);
    expect(titleButtons[0]).toHaveAttribute('aria-expanded', 'false');
    expect(titleButtons[1]).toHaveAttribute('aria-expanded', 'true');
  });
});
