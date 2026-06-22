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
