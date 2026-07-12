import { useDeviceStore } from '../store/useDeviceStore.ts';
import type { Enu, SceneFrame } from '../types/sceneFrame';
import { createSceneFrame } from '../types/sceneFrame';
import { threeToEnu } from './geo';

export interface DevicePayload {
  name: string;
  role: string;
  enu: Enu;
  power_dbm?: number;
}

export function buildDevicePayload(
  devices: ReadonlyArray<{
    name: string;
    role: string;
    x: number;
    y: number;
    z: number;
    powerDbm?: number;
  }>,
  _frame: SceneFrame,
): DevicePayload[] {
  return devices.map((device) => ({
    name: device.name,
    role: device.role,
    enu: threeToEnu([device.x, device.y, device.z]),
    ...(device.powerDbm === undefined ? {} : { power_dbm: device.powerDbm }),
  }));
}

export function getCurrentDevicePayload(frame: SceneFrame = createSceneFrame('scene-default', { lat: 0, lon: 0, alt_m: 0 })): DevicePayload[] {
  return buildDevicePayload(useDeviceStore.getState().devices, frame);
}
