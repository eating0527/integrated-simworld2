import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { TrajectoryHistoryPanel } from './TrajectoryHistoryPanel';

const bundle = {
  mission_id: 'flight-1',
  labels: ['[GPS]'],
  gps: {
    kind: 'gps' as const,
    filename: 'gps.csv',
    url: '/api/mission-bundles/flight-1/artifacts/gps',
    exists: true,
    healthy: true,
    status: 'healthy',
    header: ['time_stamp', 'lat', 'lon', 'alt', 'alt_mode'],
    size: 64,
    sha256: 'gps-sha',
  },
  noise: {
    kind: 'noise' as const,
    filename: 'noise.csv',
    url: null,
    exists: false,
    healthy: false,
    status: 'missing',
    header: null,
    size: 0,
    sha256: null,
  },
  metadata_only: false,
  trajectory: null,
};

describe('TrajectoryHistoryPanel mission bundle import', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith('/api/mission-bundles')) {
        return {
          ok: true,
          json: async () => ({ success: true, bundles: [bundle] }),
        } as Response;
      }
      if (url.endsWith('/api/mission-bundles/flight-1')) {
        return {
          ok: true,
          json: async () => ({ success: true, bundle }),
        } as Response;
      }
      if (url.endsWith('/api/mission-bundles/flight-1/artifacts/gps')) {
        return {
          ok: true,
          blob: async () => new Blob(['time_stamp,lat,lon,alt,alt_mode\n'], { type: 'text/csv' }),
        } as Response;
      }
      throw new Error(`unexpected fetch: ${url}`);
    }));
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it('applies only a healthy GPS artifact and leaves noise unset', async () => {
    const user = userEvent.setup();
    const onApplyToSimulation = vi.fn();

    render(
      <TrajectoryHistoryPanel
        selectedEventId={null}
        onSelectEvent={vi.fn()}
        onApplyToSimulation={onApplyToSimulation}
      />,
    );

    await user.click(screen.getByRole('button', { name: /restore 歷史任務清單/i }));
    await waitFor(() => expect(screen.getByText('flight-1')).toBeInTheDocument());
    expect(screen.getByText('[GPS]')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /flight-1/i }));
    await waitFor(() => expect(screen.getByRole('button', { name: '套用至模擬' })).toBeEnabled());
    await user.click(screen.getByRole('button', { name: '套用至模擬' }));

    await waitFor(() => expect(onApplyToSimulation).toHaveBeenCalledTimes(1));
    const applied = onApplyToSimulation.mock.calls[0][0] as {
      missionId: string;
      gpsFile?: File;
      noiseFile?: File;
    };
    expect(applied.missionId).toBe('flight-1');
    expect(applied.gpsFile).toBeInstanceOf(File);
    expect(applied).not.toHaveProperty('noiseFile');

    const calls = vi.mocked(fetch).mock.calls.map(([request]) => String(request));
    expect(calls.some(url => url.includes('/artifacts/noise'))).toBe(false);
  });
});
