import { useDeviceStore } from '../store/useDeviceStore.ts';

export interface DevicePayload {
  name: string;
  role: string;
  x: number;
  y: number;
  z: number;
  power_dbm: number | null;
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
): DevicePayload[] {
  return devices.map((device) => ({
    name: device.name,
    role: device.role,
    x: device.x,
    y: device.y,
    z: device.z,
    power_dbm: device.powerDbm ?? null,
  }));
}

export function getCurrentDevicePayload(): DevicePayload[] {
  return buildDevicePayload(useDeviceStore.getState().devices);
}
