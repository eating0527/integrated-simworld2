import type { ThreeElements } from '@react-three/fiber';

export type DeviceGroundMarkerRole = 'tx' | 'jammer';

interface DeviceGroundMarkerProps {
  position: [number, number, number];
  role: DeviceGroundMarkerRole;
}

const DEVICE_GROUND_MARKER_DIAMETER = 18;
const DEVICE_GROUND_MARKER_RADIUS = DEVICE_GROUND_MARKER_DIAMETER / 2;
const DEVICE_GROUND_MARKER_RING_Y = 0.35;
const DEVICE_GROUND_MARKER_FILL_Y = 0.28;

const DEVICE_GROUND_MARKER_COLORS: Record<DeviceGroundMarkerRole, string> = {
  tx: '#2ea8ff',
  jammer: '#39e66d',
};

export function getDeviceGroundMarkerVisualConfig(role: DeviceGroundMarkerRole) {
  return {
    color: DEVICE_GROUND_MARKER_COLORS[role],
    diameter: DEVICE_GROUND_MARKER_DIAMETER,
    radius: DEVICE_GROUND_MARKER_RADIUS,
    ringY: DEVICE_GROUND_MARKER_RING_Y,
    fillY: DEVICE_GROUND_MARKER_FILL_Y,
  };
}

export function DeviceGroundMarker({ position, role }: DeviceGroundMarkerProps) {
  const visual = getDeviceGroundMarkerVisualConfig(role);
  const materialProps: Pick<ThreeElements['meshBasicMaterial'], 'color' | 'transparent' | 'depthWrite'> = {
    color: visual.color,
    transparent: true,
    depthWrite: false,
  };

  return (
    <group position={position}>
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, visual.ringY, 0]}>
        <ringGeometry args={[visual.radius * 0.78, visual.radius * 1.45, 64]} />
        <meshBasicMaterial {...materialProps} opacity={0.78} />
      </mesh>

      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, visual.fillY, 0]}>
        <circleGeometry args={[visual.radius * 0.72, 48]} />
        <meshBasicMaterial {...materialProps} opacity={0.2} />
      </mesh>
    </group>
  );
}
