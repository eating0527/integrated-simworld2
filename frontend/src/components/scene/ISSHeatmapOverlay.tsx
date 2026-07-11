import { useEffect, useMemo, useState } from 'react';
import { CanvasTexture, DoubleSide, LinearFilter } from 'three';
import type { HeatmapOverlayConfig } from '../../types/heatmap';

interface OverlayGridResponse {
  success?: boolean;
  rows: number;
  cols: number;
  area_m: number;
  min_dbm: number;
  max_dbm: number;
  values: number[][];
}

export function getHeatmapOverlayPlaneConfig(overlay: Pick<HeatmapOverlayConfig, 'areaM' | 'gridBounds'>) {
  const bounds = overlay.gridBounds;
  if (!bounds) {
    return {
      width: overlay.areaM,
      height: overlay.areaM,
      position: [0, 0.12, 0] as [number, number, number],
    };
  }
  const width = bounds.max_x - bounds.min_x;
  const height = bounds.max_y - bounds.min_y;
  return {
    width,
    height,
    position: [
      bounds.min_x + width / 2,
      0.12,
      -(bounds.min_y + height / 2),
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

export function ISSHeatmapOverlay({ overlay }: { overlay: HeatmapOverlayConfig }) {
  const [grid, setGrid] = useState<OverlayGridResponse | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    setGrid(null);
    fetch(overlay.url, { signal: controller.signal })
      .then(async (response) => {
        if (!response.ok) {
          throw new Error(`overlay fetch failed: ${response.status}`);
        }
        return response.json() as Promise<OverlayGridResponse>;
      })
      .then((payload) => {
        if (!controller.signal.aborted) {
          setGrid(payload);
        }
      })
      .catch(() => {
        if (!controller.signal.aborted) {
          setGrid(null);
        }
      });
    return () => controller.abort();
  }, [overlay.url]);

  const texture = useMemo(() => {
    if (!grid) {
      return null;
    }
    const canvas = document.createElement('canvas');
    canvas.width = grid.cols;
    canvas.height = grid.rows;
    const context = canvas.getContext('2d');
    if (!context) {
      return null;
    }
    const image = context.createImageData(grid.cols, grid.rows);
    let offset = 0;
    for (let row = 0; row < grid.rows; row += 1) {
      for (let col = 0; col < grid.cols; col += 1) {
        const value = Number(grid.values[row]?.[col] ?? overlay.vminDbm);
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
    const nextTexture = new CanvasTexture(canvas);
    nextTexture.minFilter = LinearFilter;
    nextTexture.magFilter = LinearFilter;
    nextTexture.needsUpdate = true;
    return nextTexture;
  }, [grid, overlay.vmaxDbm, overlay.vminDbm]);

  useEffect(() => () => {
    texture?.dispose();
  }, [texture]);

  if (!texture) {
    return null;
  }
  const plane = getHeatmapOverlayPlaneConfig(overlay);

  return (
    <mesh rotation={[-Math.PI / 2, 0, 0]} position={plane.position} renderOrder={1}>
      <planeGeometry args={[plane.width, plane.height, 1, 1]} />
      <meshBasicMaterial
        map={texture}
        transparent
        opacity={overlay.opacity}
        depthWrite={false}
        side={DoubleSide}
        polygonOffset
        polygonOffsetFactor={-1}
      />
    </mesh>
  );
}
