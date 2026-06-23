import { afterEach, describe, expect, it } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';

import { GPSStatus } from './GPSStatus';

describe('GPSStatus', () => {
  afterEach(() => {
    cleanup();
  });

  it('shows the connection status panel title', () => {
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

    expect(screen.getByText('連線狀態')).toBeInTheDocument();
  });
});
