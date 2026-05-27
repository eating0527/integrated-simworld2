function readNumberEnv(keys: string[], fallback: number): number {
  for (const key of keys) {
    const raw = import.meta.env[key];
    if (raw === undefined || raw === null || raw === '') continue;
    const value = Number(raw);
    if (Number.isFinite(value)) return value;
  }
  return fallback;
}

export function readOriginFromEnv(
  scenePrefix: string,
  fallback: { lat: number; lon: number; alt: number }
) {
  return {
    lat: readNumberEnv([`VITE_${scenePrefix}_ORIGIN_LAT`, 'VITE_ORIGIN_LAT'], fallback.lat),
    lon: readNumberEnv([`VITE_${scenePrefix}_ORIGIN_LON`, 'VITE_ORIGIN_LON'], fallback.lon),
    alt: readNumberEnv([`VITE_${scenePrefix}_ORIGIN_ALT`, 'VITE_ORIGIN_ALT'], fallback.alt),
  };
}
