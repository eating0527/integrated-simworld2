import { Component, Suspense, useEffect, useState, type ErrorInfo, type ReactNode } from 'react';
import { Canvas } from '@react-three/fiber';
import {
  OrbitControls,
  PerspectiveCamera,
  Html,
  useGLTF,
} from '@react-three/drei';
import { ACESFilmicToneMapping } from 'three';
import { NTPUScene } from './NTPUScene';
import { NYCUScene } from './NYCUScene';
import { DynamicScene } from './DynamicScene';
import { UAVPath } from './UAVPath';
import { UAV } from './UAV';
import { Starfield } from '../ui/Starfield';
import { type SceneId, getSceneById, DEFAULT_SCENE_ID } from '@/config/scenes.config';
import { useDeviceStore } from '@/store/useDeviceStore';
import { Jam } from './Jam';
import { Tower } from './Tower';
import UAVFlight, { UAVManualDirection } from './UAVFlight';
import { CFARBeaconMarker } from './CFARBeaconMarker';
import type { CFARBeacon } from '../../types/cfar';
import type { HeatmapOverlayConfig, ISSRouteOverlayConfig } from '../../types/heatmap';
import { ISSHeatmapOverlay, type ISSHeatmapOverlayStatus } from './ISSHeatmapOverlay';
import { ISSRouteOverlay } from './ISSRouteOverlay';

function Loader({ label }: { label: string }) {
  return (
    <Html center>
      <div style={{
        color: 'white',
        fontSize: '18px',
        background: 'rgba(0,0,0,0.7)',
        padding: '16px 32px',
        borderRadius: '8px',
      }}>
        Loading {label} Scene...
      </div>
    </Html>
  );
}

function SceneLoadError({ onRetry }: { onRetry: () => void }) {
  return (
    <Html center>
      <div role="alert" style={{
        minWidth: '240px',
        padding: '16px 20px',
        color: 'white',
        textAlign: 'center',
        background: 'rgba(8, 12, 28, 0.94)',
        border: '1px solid rgba(255, 77, 106, 0.5)',
        borderRadius: '8px',
      }}>
        <div style={{ marginBottom: '12px' }}>場景載入失敗</div>
        <button type="button" onClick={onRetry}>重試</button>
      </div>
    </Html>
  );
}

interface SceneErrorBoundaryProps {
  children: ReactNode;
  onRetry: () => void;
}

interface SceneErrorBoundaryState {
  hasError: boolean;
}

class SceneErrorBoundary extends Component<SceneErrorBoundaryProps, SceneErrorBoundaryState> {
  state: SceneErrorBoundaryState = { hasError: false };

  static getDerivedStateFromError(): SceneErrorBoundaryState {
    return { hasError: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('Scene asset failed to load', error, info);
  }

  render() {
    if (this.state.hasError) return <SceneLoadError onRetry={this.props.onRetry} />;
    return this.props.children;
  }
}

interface MainSceneProps {
  uavPosition?: [number, number, number];
  uavPath?: Array<{ x: number; y: number; z: number }>;
  historicalPaths?: Array<{ id: string; label: string; color: string; path: Array<{ x: number; y: number; z: number }> }>;
  sceneId?: SceneId;
  auto?: boolean;
  manualDirection?: UAVManualDirection;
  onManualMoveDone?: () => void;
  uavAnimation?: boolean;
  onPositionUpdate?: (pos: [number, number, number]) => void;
  otherUavs?: Array<{ id: string; position: [number, number, number]; path: Array<{ x: number; y: number; z: number }> }>;
  cfarBeacons?: CFARBeacon[];
  generatedSceneModelPath?: string; // Path to dynamically generated GLB model
  heatmapOverlay?: HeatmapOverlayConfig | null;
  issRouteOverlay?: ISSRouteOverlayConfig | null;
}

export function MainScene({
  uavPosition = [0, 10, 0],
  uavPath = [],
  historicalPaths = [],
  sceneId = DEFAULT_SCENE_ID,
  auto = false,
  manualDirection = null,
  onManualMoveDone,
  uavAnimation = false,
  onPositionUpdate,
  otherUavs = [],
  cfarBeacons = [],
  generatedSceneModelPath,
  heatmapOverlay = null,
  issRouteOverlay = null,
}: MainSceneProps) {
  const sceneDef = getSceneById(sceneId);
  const cfg = sceneDef.config;
  const sceneAssetPath = generatedSceneModelPath ?? cfg.scene.modelPath;
  const [sceneRetry, setSceneRetry] = useState(0);
  const retryScene = () => {
    useGLTF.clear(sceneAssetPath);
    setSceneRetry(value => value + 1);
  };

  const devices = useDeviceStore((s) => s.devices);
  const modelVisible = useDeviceStore((s) => s.modelVisible);
  const txDevices = devices.filter((d) => d.role === 'tx');
  const jammerDevices = devices.filter((d) => d.role === 'jammer');
  const [heatmapStatus, setHeatmapStatus] = useState<ISSHeatmapOverlayStatus | null>(null);
  const [heatmapRetryKey, setHeatmapRetryKey] = useState(0);

  useEffect(() => {
    setHeatmapStatus(heatmapOverlay ? 'loading' : null);
    setHeatmapRetryKey(0);
  }, [heatmapOverlay?.url]);

  const sceneStatus = heatmapOverlay && heatmapStatus && heatmapStatus !== 'ready' ? (
    <div
      role={heatmapStatus === 'error' ? 'alert' : undefined}
      style={{
        position: 'absolute', top: 12, left: 12, zIndex: 2, color: '#fff',
        background: 'rgba(0, 0, 0, 0.72)', padding: '8px 12px', borderRadius: 6,
        fontSize: 12,
      }}
    >
      {heatmapStatus === 'loading' && 'Loading ISS heatmap…'}
      {heatmapStatus === 'empty' && 'ISS heatmap is empty.'}
      {heatmapStatus === 'error' && (
        <>
          <span>ISS heatmap failed to load.</span>{' '}
          <button type="button" onClick={() => setHeatmapRetryKey((key) => key + 1)}>Retry</button>
        </>
      )}
    </div>
  ) : null;

  return (
    <div style={{
      width: '100%',
      height: '100%',
      position: 'relative',
      background: 'radial-gradient(ellipse at bottom, #1b2735 0%, #090a0f 100%)',
      overflow: 'hidden',
    }}>
      {sceneStatus}
      <Canvas
        shadows
        gl={{
          toneMapping: ACESFilmicToneMapping,
          toneMappingExposure: 1.2,
          alpha: true,
          powerPreference: 'high-performance',
          antialias: true,
        }}
      >
        <PerspectiveCamera
          makeDefault
          position={cfg.camera.initialPosition}
          fov={cfg.camera.fov}
          near={cfg.camera.near}
          far={cfg.camera.far}
        />

        <OrbitControls
          enableDamping
          dampingFactor={0.05}
          minDistance={10}
          maxDistance={2000}
          maxPolarAngle={Math.PI / 2}
        />

        <hemisphereLight args={[0xffffff, 0x444444, 1.0]} />
        <ambientLight intensity={0.2} />
        <directionalLight
          castShadow
          position={[0, 50, 0]}
          intensity={1.5}
          shadow-mapSize-width={4096}
          shadow-mapSize-height={4096}
          shadow-camera-near={1}
          shadow-camera-far={1000}
          shadow-camera-top={500}
          shadow-camera-bottom={-500}
          shadow-camera-left={500}
          shadow-camera-right={-500}
          shadow-bias={-0.0004}
          shadow-radius={8}
        />

        <SceneErrorBoundary key={`${sceneAssetPath}:${sceneRetry}`} onRetry={retryScene}>
          <Suspense fallback={<Loader label={generatedSceneModelPath ? 'Generated' : sceneDef.labelEn} />}>
            {generatedSceneModelPath ? (
              <DynamicScene modelPath={generatedSceneModelPath} />
            ) : sceneId === 'nycu' ? (
              <NYCUScene />
            ) : (
              <NTPUScene />
            )}
          </Suspense>
        </SceneErrorBoundary>

        <Suspense fallback={null}>
          {heatmapOverlay && (
            <ISSHeatmapOverlay
              overlay={heatmapOverlay}
              retryKey={heatmapRetryKey}
              onStatusChange={setHeatmapStatus}
            />
          )}
          {issRouteOverlay && <ISSRouteOverlay overlay={issRouteOverlay} />}
          <UAVFlight
            position={uavPosition}
            scale={[10, 10, 10]}
            auto={auto}
            manualDirection={manualDirection}
            onManualMoveDone={onManualMoveDone}
            onPositionUpdate={onPositionUpdate}
            uavAnimation={uavAnimation}
            visible={modelVisible.rx}
          />
        </Suspense>

        <UAVPath path={uavPath} color="#00ff00" lineWidth={3} />

        {historicalPaths.map((track) => (
          <UAVPath key={track.id} path={track.path} color={track.color} lineWidth={2} />
        ))}

        {/* 其他連線裝置——每台一架無人機 + 軌跡 */}
        {otherUavs.map((uav, i) => {
          const COLORS = ['#ff6600', '#00aaff', '#ff00cc', '#ffff00', '#ff4444', '#44ffff'];
          const color = COLORS[i % COLORS.length];
          return (
            <Suspense key={uav.id} fallback={null}>
              <UAV position={uav.position} scale={10} />
              <UAVPath path={uav.path} color={color} lineWidth={2} />
            </Suspense>
          );
        })}

        {modelVisible.jammer && jammerDevices.map((d) => (
          <Suspense key={d.id} fallback={null}>
            <Jam position={[d.x, d.y, d.z]} scale={0.01} />
          </Suspense>
        ))}

        {modelVisible.tx && txDevices.map((d) => (
          <Suspense key={d.id} fallback={null}>
            <Tower position={[d.x, d.y, d.z]} scale={0.1} />
          </Suspense>
        ))}

        {cfarBeacons.map((beacon, index) => (
          <CFARBeaconMarker
            key={`${beacon.peak_pixel_row}:${beacon.peak_pixel_col}:${index}`}
            beacon={beacon}
            index={index}
          />
        ))}

        <Starfield starCount={180} />
      </Canvas>
    </div>
  );
}
