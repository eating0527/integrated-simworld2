import type { Enu, GridPoint, SceneFrame } from './sceneFrame';

export interface HeatmapGridBounds {
  min_x: number;
  max_x: number;
  min_y: number;
  max_y: number;
  pixel_size_x_m: number;
  pixel_size_y_m: number;
}

export interface HeatmapOverlayConfig {
  url: string;
  rows: number;
  cols: number;
  areaM: number;
  frame_id: string;
  frame: SceneFrame;
  grid: { rows: number; cols: number; pixel_size_e_m: number; pixel_size_n_m: number };
  opacity: number;
  vminDbm: number;
  vmaxDbm: number;
}

export interface ISSRoutePoint {
  time_stamp?: string;
  lat: number;
  lon: number;
  alt: number;
  alt_mode: 'amsl' | 'relative';
  frame_id: string;
  enu: Enu;
  grid: GridPoint;
}

export interface ISSSamplePoint extends ISSRoutePoint {
  noise_floor_db: number;
  used_in_sparse?: boolean;
}

export interface ISSRouteOverlayConfig {
  routePoints: ISSRoutePoint[];
  alignedPoints: ISSRoutePoint[];
  samplePoints: ISSSamplePoint[];
  routeMode: 'all' | 'aligned';
}
