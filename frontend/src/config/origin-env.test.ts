import { afterEach, describe, expect, it, vi } from 'vitest';
import { readOriginFromEnv } from './origin-env';

afterEach(() => vi.unstubAllEnvs());

describe('readOriginFromEnv', () => {
  it('does not apply a global origin to a preset scene', () => {
    vi.stubEnv('VITE_ORIGIN_LAT', '24.942349');
    vi.stubEnv('VITE_ORIGIN_LON', '121.367164');
    vi.stubEnv('VITE_ORIGIN_ALT', '0');
    vi.stubEnv('VITE_NTPU_ORIGIN_LAT', '');
    vi.stubEnv('VITE_NTPU_ORIGIN_LON', '');
    vi.stubEnv('VITE_NTPU_ORIGIN_ALT', '');

    expect(readOriginFromEnv('NTPU', {
      lat: 24.943476,
      lon: 121.370054,
      alt: 0,
    })).toEqual({
      lat: 24.943476,
      lon: 121.370054,
      alt: 0,
    });
  });

  it('allows a scene-specific origin override', () => {
    vi.stubEnv('VITE_NTPU_ORIGIN_LAT', '25');
    vi.stubEnv('VITE_NTPU_ORIGIN_LON', '122');
    vi.stubEnv('VITE_NTPU_ORIGIN_ALT', '10');

    expect(readOriginFromEnv('NTPU', {
      lat: 24.943476,
      lon: 121.370054,
      alt: 0,
    })).toEqual({ lat: 25, lon: 122, alt: 10 });
  });
});
