import type { HeatmapGridBounds } from './heatmap';

export interface CFARGrid {
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
  world_x: number;
  world_z: number;
  lat?: number;
  lon?: number;
}

export interface CFARBeacon extends CFARCluster {
  lat: number;
  lon: number;
  alt: number;
}
