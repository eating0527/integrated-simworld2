import { readOriginFromEnv } from './origin-env';

export const NYCU_CONFIG = {
  observer: readOriginFromEnv('NYCU', {
    lat: 24.967052,
    lon: 121.536335,
    alt: 0,
  }),
  scene: {
    modelPath: '/scenes/NYCU.glb',
    position: [0, 0, 0] as [number, number, number],
    scale: 1,
  },
  uav: {
    modelPath: '/models/uav.glb',
  },
  camera: {
    initialPosition: [0, 400, 500] as [number, number, number],
    fov: 60,
    near: 0.1,
    far: 10000,
  },
};
