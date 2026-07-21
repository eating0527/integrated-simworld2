import { useEffect, useMemo, useState } from 'react';
import { CanvasTexture, DoubleSide, LinearFilter } from 'three';
import type { HeatmapOverlayConfig } from '../../types/heatmap';

export type ISSHeatmapOverlayStatus = 'loading' | 'empty' | 'error' | 'ready';

type OverlayGridResponse = {
  success?: boolean;
  empty?: boolean;
  rows?: unknown;
  cols?: unknown;
  area_m?: unknown;
  min_dbm?: unknown;
  max_dbm?: unknown;
  values?: unknown;
};

export type ValidatedOverlayGrid = {
  rows: number;
  cols: number;
  area_m: number;
  min_dbm: number;
  max_dbm: number;
  values: number[][];
};

const MAX_GRID_SIZE = 512;
const MAX_GRID_CELLS = MAX_GRID_SIZE * MAX_GRID_SIZE;

function isFinitePositiveInteger(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value) && Number.isInteger(value) && value > 0;
}

export function validateHeatmapOverlayPayload(
  payload: unknown,
  expected?: Pick<HeatmapOverlayConfig, 'rows' | 'cols'>,
): { kind: 'empty' } | { kind: 'ready'; grid: ValidatedOverlayGrid } {
  if (!payload || typeof payload !== 'object') {
    throw new Error('Invalid heatmap overlay payload');
  }
  const data = payload as OverlayGridResponse;
  if (data.success === false || data.empty === true) {
    return { kind: 'empty' };
  }
  if (!isFinitePositiveInteger(data.rows) || !isFinitePositiveInteger(data.cols)
    || data.rows > MAX_GRID_SIZE || data.cols > MAX_GRID_SIZE || data.rows * data.cols > MAX_GRID_CELLS
    || (expected && (data.rows !== expected.rows || data.cols !== expected.cols))) {
    throw new Error('Invalid heatmap overlay dimensions');
  }
  if (typeof data.area_m !== 'number' || !Number.isFinite(data.area_m)
    || typeof data.min_dbm !== 'number' || !Number.isFinite(data.min_dbm)
    || typeof data.max_dbm !== 'number' || !Number.isFinite(data.max_dbm)
    || data.min_dbm >= data.max_dbm || !Array.isArray(data.values) || data.values.length !== data.rows) {
    throw new Error('Invalid heatmap overlay metadata');
  }
  const values = data.values.map((row) => {
    if (!Array.isArray(row) || row.length !== data.cols
      || row.some((value) => typeof value !== 'number' || !Number.isFinite(value))) {
      throw new Error('Invalid heatmap overlay values');
    }
    return row as number[];
  });
  return { kind: 'ready', grid: {
    rows: data.rows,
    cols: data.cols,
    area_m: data.area_m,
    min_dbm: data.min_dbm,
    max_dbm: data.max_dbm,
    values,
  } };
}

export function getHeatmapOverlayPlaneConfig(overlay: Pick<HeatmapOverlayConfig, 'areaM' | 'frame'>) {
  const bounds = overlay.frame.extent;
  const width = bounds.max_e - bounds.min_e;
  const height = bounds.max_n - bounds.min_n;
  return {
    width: width || overlay.areaM,
    height: height || overlay.areaM,
    position: [
      bounds.min_e + width / 2,
      0.12,
      -(bounds.min_n + height / 2) || 0,
    ] as [number, number, number],
  };
}

function clamp01(value: number) {
  return Math.min(1, Math.max(0, value));
}

function jetColor(t: number) {
  const x = clamp01(t);
  const r = clamp01(1.5 - Math.abs(4 * x - 3));
  const g = clamp01(1.5 - Math.abs(4 * x - 2));
  const b = clamp01(1.5 - Math.abs(4 * x - 1));
  return [r, g, b] as const;
}

interface ISSHeatmapOverlayProps {
  overlay: HeatmapOverlayConfig;
  onStatusChange?: (status: ISSHeatmapOverlayStatus) => void;
  retryKey?: number;
}

type RequestState =
  | { status: 'loading' }
  | { status: 'empty' }
  | { status: 'error' }
  | { status: 'ready'; grid: ValidatedOverlayGrid };

export function ISSHeatmapOverlay({ overlay, onStatusChange, retryKey = 0 }: ISSHeatmapOverlayProps) {
  const [request, setRequest] = useState<RequestState>({ status: 'loading' });

  useEffect(() => {
    const controller = new AbortController();
    setRequest({ status: 'loading' });
    try {
      if (!Number.isFinite(overlay.vminDbm) || !Number.isFinite(overlay.vmaxDbm)
        || overlay.vminDbm >= overlay.vmaxDbm) throw new Error('Invalid heatmap display range');
    } catch {
      setRequest({ status: 'error' });
      return () => controller.abort();
    }
    fetch(overlay.url, { signal: controller.signal })
      .then(async (response) => {
        if (!response.ok) throw new Error(`overlay fetch failed: ${response.status}`);
        return validateHeatmapOverlayPayload(await response.json(), overlay);
      })
      .then((result) => {
        if (!controller.signal.aborted) {
          setRequest(result.kind === 'empty' ? { status: 'empty' } : { status: 'ready', grid: result.grid });
        }
      })
      .catch(() => {
        if (!controller.signal.aborted) setRequest({ status: 'error' });
      });
    return () => controller.abort();
  }, [overlay.url, overlay.rows, overlay.cols, overlay.vmaxDbm, overlay.vminDbm, retryKey]);

  const rendered = useMemo(() => {
    if (request.status !== 'ready') return { texture: null, error: null };
    try {
      const canvas = document.createElement('canvas');
      canvas.width = request.grid.cols;
      canvas.height = request.grid.rows;
      const context = canvas.getContext('2d');
      if (!context) throw new Error('Heatmap canvas context unavailable');
      const image = context.createImageData(request.grid.cols, request.grid.rows);
      let offset = 0;
      for (let row = 0; row < request.grid.rows; row += 1) {
        for (let col = 0; col < request.grid.cols; col += 1) {
          const value = request.grid.values[row][col];
          const normalized = clamp01((value - overlay.vminDbm) / Math.max(1e-6, overlay.vmaxDbm - overlay.vminDbm));
          const [r, g, b] = jetColor(normalized);
          const alpha = normalized <= 0.02 ? 0 : Math.round(255 * Math.pow(normalized, 1.35));
          image.data[offset] = Math.round(r * 255);
          image.data[offset + 1] = Math.round(g * 255);
          image.data[offset + 2] = Math.round(b * 255);
          image.data[offset + 3] = alpha;
          offset += 4;
        }
      }
      context.putImageData(image, 0, 0);
      const texture = new CanvasTexture(canvas);
      texture.minFilter = LinearFilter;
      texture.magFilter = LinearFilter;
      texture.needsUpdate = true;
      return { texture, error: null };
    } catch (error) {
      return { texture: null, error };
    }
  }, [request, overlay.vmaxDbm, overlay.vminDbm]);

  useEffect(() => {
    const status = rendered.error ? 'error' : request.status === 'ready' && rendered.texture ? 'ready' : request.status;
    onStatusChange?.(status);
  }, [onStatusChange, rendered.error, rendered.texture, request.status]);

  useEffect(() => () => rendered.texture?.dispose(), [rendered.texture]);

  if (!rendered.texture) return null;
  const plane = getHeatmapOverlayPlaneConfig(overlay);
  return (
    <mesh rotation={[-Math.PI / 2, 0, 0]} position={plane.position} renderOrder={1}>
      <planeGeometry args={[plane.width, plane.height, 1, 1]} />
      <meshBasicMaterial map={rendered.texture} transparent opacity={overlay.opacity} depthWrite={false} side={DoubleSide} polygonOffset polygonOffsetFactor={-1} />
    </mesh>
  );
}
