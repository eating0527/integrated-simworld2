import { afterEach, describe, expect, it } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { GPSStatus } from './GPSStatus';

function renderPanel() {
  render(
    <GPSStatus
      myDeviceId="device-123456"
      deviceName="Drone"
      onRenameClick={() => {}}
      allDevices={new Map()}
      uavPath={[]}
      onClearPath={() => {}}
      connectionStatus="connected"
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
});
