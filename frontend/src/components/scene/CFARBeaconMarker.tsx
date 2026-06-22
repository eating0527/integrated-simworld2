import { Html } from '@react-three/drei';
import type { CFARBeacon } from '../../types/cfar';

interface CFARBeaconMarkerProps {
  beacon: CFARBeacon;
  index: number;
}

function formatCoord(value: number) {
  return value.toFixed(6);
}

function formatPower(value: number) {
  return `${value.toFixed(1)} dBm`;
}

const BEACON_DIAMETER = 18;
const BEACON_HEIGHT = 3600;
const BEACON_RADIUS = BEACON_DIAMETER / 2;
const BEACON_LABEL_MIN_WIDTH = 780;
const BEACON_LABEL_PADDING = '8px 12px';
const BEACON_LABEL_FONT_SIZE = 250;

export function getCFARBeaconVisualConfig(_cluster: { size: number }) {
  return {
    diameter: BEACON_DIAMETER,
    radius: BEACON_RADIUS,
    height: BEACON_HEIGHT,
  };
}

export function getCFARBeaconLabelVisualConfig() {
  return {
    minWidth: BEACON_LABEL_MIN_WIDTH,
    padding: BEACON_LABEL_PADDING,
    fontSize: BEACON_LABEL_FONT_SIZE,
  };
}

export function CFARBeaconMarker({ beacon, index }: CFARBeaconMarkerProps) {
  const { radius, height } = getCFARBeaconVisualConfig(beacon);
  const labelVisual = getCFARBeaconLabelVisualConfig();
  const label_1 = `訊號強度：${formatPower(beacon.peak_power_dbm)}`;
  const label_2 = `座標：${formatCoord(beacon.lat)}, ${formatCoord(beacon.lon)}`;

  return (
    <group position={[beacon.world_x, 0, beacon.world_z]}>
      <mesh position={[0, height / 2, 0]}>
        <cylinderGeometry args={[radius * 0.34, radius * 0.34, height, 48, 1, true]} />
        <meshBasicMaterial color="#ff1717" transparent opacity={0.34} depthWrite={false} />
      </mesh>

      <mesh position={[0, height / 2, 0]}>
        <cylinderGeometry args={[radius, radius, height, 56, 1, true]} />
        <meshBasicMaterial color="#ff3333" transparent opacity={0.13} depthWrite={false} />
      </mesh>

      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.35, 0]}>
        <ringGeometry args={[radius * 0.78, radius * 1.45, 64]} />
        <meshBasicMaterial color="#ff3434" transparent opacity={0.78} depthWrite={false} />
      </mesh>

      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.28, 0]}>
        <circleGeometry args={[radius * 0.72, 48]} />
        <meshBasicMaterial color="#ff2020" transparent opacity={0.32} depthWrite={false} />
      </mesh>

      <mesh position={[0, height + 7, 0]}>
        <sphereGeometry args={[radius * 0.72, 24, 24]} />
        <meshBasicMaterial color="#ff4040" transparent opacity={0.9} />
      </mesh>

      <Html position={[0, Math.min(height * 0.25, 260), 0]} center distanceFactor={30} transform={false}>
        <div style={{
          minWidth: labelVisual.minWidth,
          padding: labelVisual.padding,
          borderRadius: 6,
          border: '1px solid rgba(255,85,85,.68)',
          background: 'rgba(24,6,8,.82)',
          boxShadow: '0 0 20px rgba(255,35,35,.28)',
          color: '#ffe8e8',
          fontSize: labelVisual.fontSize,
          fontWeight: 700,
          lineHeight: 1.25,
          textAlign: 'center',
          pointerEvents: 'none',
          whiteSpace: 'nowrap',
        }}>
          <div style={{ color: '#ff6a6a', marginBottom: 2 }}>干擾源 # {index + 1}</div>
          <div>{label_1}</div>
          <div>{label_2}</div>
        </div>
      </Html>
    </group>
  );
}
