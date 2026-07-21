export type AltMode = 'amsl' | 'relative';

export interface Enu {
  east_m: number;
  north_m: number;
  up_m: number;
}

export interface SceneFrame {
  frame_version?: number;
  frame_id: string;
  origin: { lat: number; lon: number; alt_m: number };
  alt_mode: AltMode;
  axis?: string;
  units?: string;
  extent: { min_e: number; max_e: number; min_n: number; max_n: number };
  display_margin_m: number;
  grid: { rows: number; cols: number; pixel_size_e_m: number; pixel_size_n_m: number };
}

export interface GridPoint {
  row: number | null;
  col: number | null;
  inside_extent: boolean;
  displayable: boolean;
}

export function createSceneFrame(
  frame_id: string,
  origin: SceneFrame['origin'],
  alt_mode: AltMode = 'amsl',
): SceneFrame {
  return {
    frame_version: 1,
    frame_id,
    origin,
    alt_mode,
    axis: 'ENU',
    units: 'm',
    extent: { min_e: -256, max_e: 256, min_n: -256, max_n: 256 },
    display_margin_m: 32,
    grid: { rows: 128, cols: 128, pixel_size_e_m: 4, pixel_size_n_m: 4 },
  };
}

export function parseSceneFrame(value: unknown): SceneFrame | null {
  const raw = (value && typeof value === 'object' && 'frame' in value)
    ? (value as { frame?: unknown }).frame
    : value;
  if (!raw || typeof raw !== 'object') return null;
  const frame = raw as Partial<SceneFrame>;
  if (!frame.frame_id || !frame.origin || !frame.extent || !frame.grid) return null;
  if (frame.alt_mode !== 'amsl' && frame.alt_mode !== 'relative') return null;
  if (frame.frame_version !== 1 || frame.axis !== 'ENU' || frame.units !== 'm') return null;
  if (frame.extent.min_e !== -256 || frame.extent.max_e !== 256
    || frame.extent.min_n !== -256 || frame.extent.max_n !== 256
    || frame.display_margin_m !== 32) return null;
  if (frame.grid.rows !== 128 || frame.grid.cols !== 128
    || frame.grid.pixel_size_e_m !== 4 || frame.grid.pixel_size_n_m !== 4) return null;
  return frame as SceneFrame;
}
