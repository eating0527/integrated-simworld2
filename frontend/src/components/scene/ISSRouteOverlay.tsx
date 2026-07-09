import { useMemo } from 'react';
import { Line } from '@react-three/drei';
import type { ISSRouteOverlayConfig, ISSRoutePoint } from '../../types/heatmap';

const MIN_HEIGHT = 4;
const NOISE_MIN_DBM = -90;
const NOISE_MAX_DBM = -15;

function clamp01(value: number) {
  return Math.min(1, Math.max(0, value));
}

function pointToScene(point: ISSRoutePoint): [number, number, number] | null {
  const x = Number(point.world_x);
  const z = Number(point.world_z);
  if (!Number.isFinite(x) || !Number.isFinite(z)) {
    return null;
  }
  const alt = Number(point.alt);
  return [x, Math.max(Number.isFinite(alt) ? alt : 0, MIN_HEIGHT), z];
}

export function getIssRouteLinePoints(overlay: ISSRouteOverlayConfig): [number, number, number][] {
  const source = overlay.routeMode === 'aligned' ? overlay.alignedPoints : overlay.routePoints;
  return source.flatMap((point) => {
    const scenePoint = pointToScene(point);
    return scenePoint ? [scenePoint] : [];
  });
}

export function getIssNoiseColor(noiseDbm: number): string {
  const value = Number.isFinite(noiseDbm) ? noiseDbm : NOISE_MIN_DBM;
  const t = clamp01((value - NOISE_MIN_DBM) / (NOISE_MAX_DBM - NOISE_MIN_DBM));
  const r = clamp01(1.5 - Math.abs(4 * t - 3));
  const g = clamp01(1.5 - Math.abs(4 * t - 2));
  const b = clamp01(1.5 - Math.abs(4 * t - 1));
  return `#${[r, g, b].map((channel) => Math.round(channel * 255).toString(16).padStart(2, '0')).join('')}`;
}

export function ISSRouteOverlay({ overlay }: { overlay: ISSRouteOverlayConfig }) {
  const linePoints = useMemo(() => getIssRouteLinePoints(overlay), [overlay]);
  const sampleMarkers = useMemo(() => (
    overlay.samplePoints.flatMap((point, index) => {
      const position = pointToScene(point);
      return position ? [{ point, index, position }] : [];
    })
  ), [overlay]);

  return (
    <group>
      {linePoints.length >= 2 && (
        <Line
          points={linePoints}
          color="#ffffff"
          lineWidth={2}
          transparent
          opacity={0.95}
          depthWrite={false}
        />
      )}
      {sampleMarkers.map(({ point, index, position }) => (
        <mesh key={`${point.time_stamp ?? 'sample'}:${index}`} position={position}>
          <sphereGeometry args={[2.2, 12, 8]} />
          <meshBasicMaterial color={getIssNoiseColor(point.noise_floor_db)} />
        </mesh>
      ))}
    </group>
  );
}
