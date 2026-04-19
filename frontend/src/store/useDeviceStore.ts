import { create } from 'zustand';
import type { Device, DeviceRole } from '../types/device';

interface DeviceStore {
  devices: Device[];
  deviceDefaults: Record<string, DeviceDefault>;
  addDevice: (role: DeviceRole) => void;
  removeDevice: (id: string) => void;
  updateDevice: (id: string, patch: Partial<Omit<Device, 'id' | 'role'>>) => void;
  saveDeviceDefault: (id: string) => void;
  applyDeviceDefault: (id: string) => void;
  zeroDevice: (id: string) => void;
}

interface DeviceDefault {
  x: number;
  y: number;
  z: number;
  powerDbm?: number;
}

let _nextId = 1;
function genId() {
  return `dev-${_nextId++}`;
}

function countByRole(devices: Device[], role: DeviceRole): number {
  return devices.filter((d) => d.role === role).length;
}

const DEFAULT_TX_POWER_DBM = 60;
const DEFAULT_JAM_POWER_DBM = 60;

function defaultPowerDbm(role: DeviceRole): number | undefined {
  if (role === 'tx') return DEFAULT_TX_POWER_DBM;
  if (role === 'jammer') return DEFAULT_JAM_POWER_DBM;
  return undefined;
}

const DEFAULT_DEVICES: Device[] = [
  {
    id: 'dev-tx-0',
    name: 'tx-0',
    role: 'tx',
    x: -75,
    y: 0,
    z: 75,
    powerDbm: DEFAULT_TX_POWER_DBM,
  },
  {
    id: 'dev-rx-0',
    name: 'rx-0',
    role: 'rx',
    x: -30,
    y: 10,
    z: 175,
  },
  {
    id: 'dev-jam-0',
    name: 'jam-0',
    role: 'jammer',
    x: -150,
    y: 0,
    z: 170,
    powerDbm: DEFAULT_JAM_POWER_DBM,
  },
];

function makeDeviceDefault(device: Device): DeviceDefault {
  return {
    x: device.x,
    y: device.y,
    z: device.z,
    ...(device.powerDbm !== undefined ? { powerDbm: device.powerDbm } : {}),
  };
}

function makeDeviceDefaults(devices: Device[]): Record<string, DeviceDefault> {
  return devices.reduce<Record<string, DeviceDefault>>((defaults, device) => {
    defaults[device.id] = makeDeviceDefault(device);
    return defaults;
  }, {});
}

export const useDeviceStore = create<DeviceStore>((set) => ({
  devices: DEFAULT_DEVICES,
  deviceDefaults: makeDeviceDefaults(DEFAULT_DEVICES),

  addDevice: (role) => {
    set((state) => {
      const count = countByRole(state.devices, role);
      const prefix = role === 'tx' ? 'tx' : role === 'rx' ? 'rx' : 'jam';
      const powerDbm = defaultPowerDbm(role);
      const newDevice: Device = {
        id: genId(),
        name: `${prefix}-${count}`,
        role,
        x: 0,
        y: 0,
        z: 0,
        ...(powerDbm !== undefined ? { powerDbm } : {}),
      };
      return {
        devices: [...state.devices, newDevice],
        deviceDefaults: {
          ...state.deviceDefaults,
          [newDevice.id]: makeDeviceDefault(newDevice),
        },
      };
    });
  },

  removeDevice: (id) => {
    set((state) => {
      const { [id]: _removedDefault, ...deviceDefaults } = state.deviceDefaults;
      return {
        devices: state.devices.filter((d) => d.id !== id),
        deviceDefaults,
      };
    });
  },

  updateDevice: (id, patch) => {
    set((state) => ({
      devices: state.devices.map((d) => (d.id === id ? { ...d, ...patch } : d)),
    }));
  },

  saveDeviceDefault: (id) => {
    set((state) => {
      const device = state.devices.find((d) => d.id === id);
      if (!device) return state;

      return {
        deviceDefaults: {
          ...state.deviceDefaults,
          [id]: makeDeviceDefault(device),
        },
      };
    });
  },

  applyDeviceDefault: (id) => {
    set((state) => {
      const savedDefault = state.deviceDefaults[id];
      if (!savedDefault) return state;

      return {
        devices: state.devices.map((device) => {
          if (device.id !== id) return device;

          return {
            ...device,
            x: savedDefault.x,
            y: savedDefault.y,
            z: savedDefault.z,
            ...(savedDefault.powerDbm !== undefined ? { powerDbm: savedDefault.powerDbm } : {}),
          };
        }),
      };
    });
  },

  zeroDevice: (id) => {
    set((state) => ({
      devices: state.devices.map((device) => {
        if (device.id !== id) return device;

        const savedDefault = state.deviceDefaults[id];
        const powerDbm = savedDefault?.powerDbm ?? defaultPowerDbm(device.role);

        return {
          ...device,
          x: 0,
          y: 0,
          z: 0,
          ...(powerDbm !== undefined ? { powerDbm } : {}),
        };
      }),
    }));
  },
}));
