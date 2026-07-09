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
  gridBounds?: HeatmapGridBounds;
  opacity: number;
  vminDbm: number;
  vmaxDbm: number;
}

export interface ISSRoutePoint {
  time_stamp?: string;
  lat: number;
  lon: number;
  alt: number;
  row: number;
  col: number;
  world_x: number;
  world_z: number;
  in_bounds?: boolean;
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
