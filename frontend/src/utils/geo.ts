import type { AltMode, Enu, GridPoint, SceneFrame } from '../types/sceneFrame';

const METERS_PER_DEGREE_LAT = 111_320;

function metersPerDegree(frame: SceneFrame) {
  return {
    lat: METERS_PER_DEGREE_LAT,
    lon: Math.max(1, METERS_PER_DEGREE_LAT * Math.cos(frame.origin.lat * Math.PI / 180)),
  };
}

export function gpsToEnu(
  gps: { lat: number; lon: number; alt: number },
  frame: SceneFrame,
  altMode: AltMode = frame.alt_mode,
): Enu {
  const meters = metersPerDegree(frame);
  return {
    east_m: (gps.lon - frame.origin.lon) * meters.lon,
    north_m: (gps.lat - frame.origin.lat) * meters.lat,
    up_m: altMode === 'amsl' ? gps.alt - frame.origin.alt_m : gps.alt,
  };
}

export function enuToGps(enu: Enu, frame: SceneFrame, altMode: AltMode = frame.alt_mode) {
  const meters = metersPerDegree(frame);
  return {
    lat: frame.origin.lat + enu.north_m / meters.lat,
    lon: frame.origin.lon + enu.east_m / meters.lon,
    alt: altMode === 'amsl' ? enu.up_m + frame.origin.alt_m : enu.up_m,
  };
}

export function enuToThree(enu: Enu): [number, number, number] {
  return [enu.east_m, enu.up_m, -enu.north_m];
}

export function threeToEnu([x, y, z]: [number, number, number]): Enu {
  return { east_m: x, north_m: -z, up_m: y };
}

export function enuToGrid(enu: Enu, frame: SceneFrame): GridPoint {
  const { min_e, max_e, min_n, max_n } = frame.extent;
  const inside_extent = min_e <= enu.east_m && enu.east_m < max_e && min_n <= enu.north_m && enu.north_m < max_n;
  const displayable = (
    min_e - frame.display_margin_m <= enu.east_m && enu.east_m < max_e + frame.display_margin_m
    && min_n - frame.display_margin_m <= enu.north_m && enu.north_m < max_n + frame.display_margin_m
  );
  return {
    row: inside_extent
      ? Math.min(frame.grid.rows - 1, Math.floor((max_n - enu.north_m) / frame.grid.pixel_size_n_m))
      : null,
    col: inside_extent
      ? Math.min(frame.grid.cols - 1, Math.floor((enu.east_m - min_e) / frame.grid.pixel_size_e_m))
      : null,
    inside_extent,
    displayable,
  };
}
