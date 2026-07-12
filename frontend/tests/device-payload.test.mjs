import assert from 'node:assert/strict';
import { describe, it } from 'vitest';

import { useDeviceStore } from '../src/store/useDeviceStore.ts';
import { getCurrentDevicePayload } from '../src/utils/devicePayload.ts';

describe('device payload', () => {
  it('reflects the current jammer device state', () => {
    const originalDevices = useDeviceStore.getState().devices;
    const jammer = originalDevices.find((device) => device.role === 'jammer');

    assert.ok(jammer, 'expected default jammer device');

    useDeviceStore.getState().updateDevice(jammer.id, {
      x: 321,
      y: 12,
      z: -45,
      powerDbm: 77,
    });

    const payload = getCurrentDevicePayload({
      frame_id: 'scene-test',
      origin: { lat: 24, lon: 121, alt_m: 0 },
      alt_mode: 'amsl',
      extent: { min_e: -256, max_e: 256, min_n: -256, max_n: 256 },
      display_margin_m: 32,
      grid: { rows: 128, cols: 128, pixel_size_e_m: 4, pixel_size_n_m: 4 },
    });
    const updatedJammer = payload.find((device) => device.role === 'jammer');

    assert.deepEqual(
      updatedJammer,
      {
        name: jammer.name,
        role: 'jammer',
        enu: { east_m: 321, north_m: 45, up_m: 12 },
        power_dbm: 77,
      },
    );
  });
});
