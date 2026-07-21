import type { HeatmapGridBounds } from './heatmap';
import type { Enu, GridPoint, SceneFrame } from './sceneFrame';

export interface CFARGrid {
  frame_id: string;
  frame: SceneFrame;
  rows: number;
  cols: number;
  area_m: number;
  pixel_size_m: number;
  pixel_size_x_m?: number;
  pixel_size_y_m?: number;
  grid_bounds?: HeatmapGridBounds;
}

export interface CFARCluster {
  peak_pixel_row: number;
  peak_pixel_col: number;
  peak_power_dbm: number;
  mean_power_dbm: number;
  size: number;
  frame_id: string;
  frame?: SceneFrame;
  enu: Enu;
  grid: GridPoint;
  lat: number;
  lon: number;
  alt: number;
  alt_mode?: 'amsl' | 'relative';
}

export interface CFARBeacon extends CFARCluster {
}
