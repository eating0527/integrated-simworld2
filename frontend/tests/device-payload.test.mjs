import assert from 'node:assert/strict';

import { useDeviceStore } from '../src/store/useDeviceStore.ts';
import { getCurrentDevicePayload } from '../src/utils/devicePayload.ts';

const originalDevices = useDeviceStore.getState().devices;
const jammer = originalDevices.find((device) => device.role === 'jammer');

assert.ok(jammer, 'expected default jammer device');

useDeviceStore.getState().updateDevice(jammer.id, {
  x: 321,
  y: 12,
  z: -45,
  powerDbm: 77,
});

const payload = getCurrentDevicePayload();
const updatedJammer = payload.find((device) => device.role === 'jammer');

assert.deepEqual(
  updatedJammer,
  {
    name: jammer.name,
    role: 'jammer',
    x: 321,
    y: 12,
    z: -45,
    power_dbm: 77,
  },
);
