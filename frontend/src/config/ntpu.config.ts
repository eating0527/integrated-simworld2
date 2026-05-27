import { readOriginFromEnv } from './origin-env';

export const NTPU_CONFIG = {
  observer: readOriginFromEnv('NTPU', {
    lat: 24.943476,
    lon: 121.370054,
    alt: 0,
  }),
  scene: {
    modelPath: '/scenes/NTPU.glb',
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
