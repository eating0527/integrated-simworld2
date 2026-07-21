function readNumberEnv(key: string, fallback: number): number {
  const raw = import.meta.env[key];
  if (raw === undefined || raw === null || raw === '') return fallback;
  const value = Number(raw);
  return Number.isFinite(value) ? value : fallback;
}

export function readOriginFromEnv(
  scenePrefix: string,
  fallback: { lat: number; lon: number; alt: number }
) {
  return {
    lat: readNumberEnv(`VITE_${scenePrefix}_ORIGIN_LAT`, fallback.lat),
    lon: readNumberEnv(`VITE_${scenePrefix}_ORIGIN_LON`, fallback.lon),
    alt: readNumberEnv(`VITE_${scenePrefix}_ORIGIN_ALT`, fallback.alt),
  };
}
