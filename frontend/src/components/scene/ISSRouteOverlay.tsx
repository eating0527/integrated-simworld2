import { useMemo } from 'react';
import { Line } from '@react-three/drei';
import type { ISSRouteOverlayConfig, ISSRoutePoint } from '../../types/heatmap';
import { enuToThree } from '../../utils/geo';

const NOISE_MIN_DBM = -90;
const NOISE_MAX_DBM = -15;

function clamp01(value: number) {
  return Math.min(1, Math.max(0, value));
}

function pointToScene(point: ISSRoutePoint): [number, number, number] | null {
  if (point.grid?.displayable === false) {
    return null;
  }
  const { east_m, north_m, up_m } = point.enu;
  if (![east_m, north_m, up_m].every(Number.isFinite)) return null;
  return enuToThree(point.enu);
}

export function getIssRouteLinePoints(overlay: ISSRouteOverlayConfig): [number, number, number][] {
  const source = overlay.routeMode === 'aligned' ? overlay.alignedPoints : overlay.routePoints;
  return source.flatMap((point) => {
    const scenePoint = pointToScene(point);
    return scenePoint ? [scenePoint] : [];
  });
}

export function getIssNoiseMarkerKind(noiseDbm: number | null | undefined): 'sample' | 'empty' {
  return typeof noiseDbm === 'number' && Number.isFinite(noiseDbm) ? 'sample' : 'empty';
}

export function getIssNoiseColor(noiseDbm: number | null | undefined): string {
  const value = getIssNoiseMarkerKind(noiseDbm) === 'sample' ? Number(noiseDbm) : NOISE_MIN_DBM;
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
  const emptyMarkers = useMemo(() => (
    overlay.alignedPoints.flatMap((point, index) => {
      if (getIssNoiseMarkerKind(point.noise_floor_db) !== 'empty') return [];
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
      {emptyMarkers.map(({ point, index, position }) => (
        <mesh key={`${point.time_stamp ?? 'empty'}:${index}`} position={position} rotation={[Math.PI / 2, 0, 0]}>
          <ringGeometry args={[2.2, 2.8, 16]} />
          <meshBasicMaterial color="#ffffff" transparent opacity={0.95} depthWrite={false} />
        </mesh>
      ))}
    </group>
  );
}
