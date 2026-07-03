/**
 * App.tsx — 應用程式主元件
 *
 * 職責：
 *  1. 取得本地 GPS（手機端，傳給 useGPSSync 發送）
 *  2. 從 useGPSSync 接收其他裝置的 GPS（電腦端顯示）
 *  3. 將 GPS 轉成 ENU 三維座標，驅動 UAV 位置與軌跡
 *  4. 管理照片列表（初始載入 + WebSocket 即時更新）
 *  5. 渲染 3D 場景、GPS HUD、拍照按鈕、照片歷史
 *  6. 支援動態場景加載（使用者點選地圖生成）
 */
import { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { MainScene } from './components/scene/MainScene';
import { CameraUpload } from './components/ui/CameraUpload';
import { PhotoViewer } from './components/ui/PhotoViewer';
import { GPSStatus } from './components/ui/GPSStatus';
import { useGPSSync } from './hooks/useGPSSync';
import { useGeneratedScenes } from './hooks/useGeneratedScene';
import { latLonToENU, worldXZToLatLon } from './utils/geo';
import { ControllerScreenPanel } from './components/ui/ControllerScreenPanel';
import { SimulationPanel } from './components/ui/SimulationPanel';
import { SceneSwitcher, type SelectedScene } from './components/ui/SceneSwitcher';
import { type SceneId, DEFAULT_SCENE_ID, getSceneById } from './config/scenes.config';
import { DevicePanel } from './components/ui/DevicePanel';
import { UAVControlPanel } from './components/ui/UAVControlPanel';
import { AircraftTelemetry } from './components/ui/AircraftTelemetry';
import { USRPTelemetry } from './components/ui/USRPTelemetry';
import { useManualControl } from './hooks/useManualControl';
import { useDeviceStore } from './store/useDeviceStore';
import type { CFARBeacon, CFARCluster } from './types/cfar';
import type { HeatmapOverlayConfig } from './types/heatmap';

// ── 環境變數 ────────────────────────────────────────────────────────

const SCALE = Number(import.meta.env.VITE_SCENE_SCALE ?? 1);
// 空字串時使用相對路徑，讓 Vite proxy 接管（本地開發用）
const API = import.meta.env.VITE_API_URL || '';

// 高度視覺增益（現實 1m → 場景 ALT_GAIN 單位）
const ALT_GAIN = 2.14;

// ── Types ───────────────────────────────────────────────────────────
interface LocalGPS {
  lat: number;
  lon: number;
  alt: number;
  accuracy: number;
}

interface Photo {
  url: string;
  timestamp: string;
  filename: string;
  latitude?: number | null;
  longitude?: number | null;
  altitude?: number | null;
  deviceId?: string | null;
}

interface GeoOrigin {
  lat: number;
  lon: number;
  alt: number;
}

function getInitialRxPosition(): [number, number, number] {
  const rx = useDeviceStore.getState().devices.find((d) => d.id === 'dev-rx-0');
  return rx ? [rx.x, rx.y, rx.z] : [0, 0, 0];
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

function getGeneratedSceneOrigin(metadata: Record<string, unknown> | null | undefined): GeoOrigin | null {
  if (!metadata) return null;

  const lat = metadata.lat;
  const lon = metadata.lon;
  const alt = metadata.alt;

  if (!isFiniteNumber(lat) || !isFiniteNumber(lon)) {
    return null;
  }

  return {
    lat,
    lon,
    alt: isFiniteNumber(alt) ? alt : 0,
  };
}

// ── App ─────────────────────────────────────────────────────────────
export function App() {
  const isMobile = /iPhone|iPad|iPod|Android/i.test(navigator.userAgent);
  const [fromMap] = useState(() => {
    const search = new URLSearchParams(window.location.search);
    return search.get('fromMap') === '1';
  });

  // ── 入口策略：預設先進地圖頁，只有從 my_map.html 回來才進 React ─────────
  const needsMapSelection = !fromMap;

  useEffect(() => {
    if (!needsMapSelection) return;
    window.location.replace(`${window.location.origin}/my_map.html`);
  }, [needsMapSelection]);

  // 自動重定向期間顯示提示
  if (needsMapSelection) {
    return (
      <div style={{
        width: '100vw',
        height: '100dvh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: 'linear-gradient(135deg, #1e3c72 0%, #2a5298 100%)',
        color: 'white',
        fontSize: '18px',
        flexDirection: 'column',
        gap: '20px',
      }}>
        <div style={{ textAlign: 'center' }}>
          <h1 style={{ marginBottom: '10px' }}>🗺️ 場景生成系統</h1>
          <p>正在前往地圖選點頁面...</p>
          <p style={{ fontSize: '14px', opacity: 0.7 }}>選完後會自動建立 blosm 任務並回到 React</p>
        </div>
      </div>
    );
  }

  // ── UAV Control Panel 狀態 ───────────────────────────────────────
  const [auto, setAuto] = useState(false);
  const [uavAnimation, setUavAnimation] = useState(false);
  const { manualDirection, handleManualControl, resetManualControl } = useManualControl();

  const handleToggleAuto = useCallback(() => {
    setAuto(prev => !prev);
    resetManualControl();
  }, [resetManualControl]);

  const handleManualMoveDone = useCallback(() => {
    resetManualControl();
  }, [resetManualControl]);

  // ── 生成場景管理（地圖點選生成）─────────────────────────────────
  const generatedScenes = useGeneratedScenes();

  // ── 場景管理 ────────────────────────────────────────────────
  const [selectedScene, setSelectedScene] = useState<SelectedScene>({
    source: 'preset',
    id: DEFAULT_SCENE_ID,
  });
  const [lastPresetSceneId, setLastPresetSceneId] = useState<SceneId>(DEFAULT_SCENE_ID);
  const activeGeneratedScene = selectedScene.source === 'generated'
    ? generatedScenes.scenes.find(scene => scene.taskId === selectedScene.taskId) ?? null
    : null;
  const renderSceneId = selectedScene.source === 'preset' ? selectedScene.id : lastPresetSceneId;
  const sceneDef = getSceneById(renderSceneId);
  const defaultOrigin = useMemo<GeoOrigin>(() => ({
    lat: sceneDef.config.observer.lat,
    lon: sceneDef.config.observer.lon,
    alt: sceneDef.config.observer.alt,
  }), [
    sceneDef.config.observer.alt,
    sceneDef.config.observer.lat,
    sceneDef.config.observer.lon,
  ]);
  const pickedSceneOrigin = useMemo(() => {
    if (!activeGeneratedScene?.location) return null;
    return getGeneratedSceneOrigin({
      lat: activeGeneratedScene.location.lat,
      lon: activeGeneratedScene.location.lon,
      alt: 0,
    });
  }, [activeGeneratedScene?.location]);
  const activeOrigin = useMemo(
    () => (activeGeneratedScene && pickedSceneOrigin ? pickedSceneOrigin : defaultOrigin),
    [activeGeneratedScene, defaultOrigin, pickedSceneOrigin]
  );
  const activeOriginKey = `${activeOrigin.lat}:${activeOrigin.lon}:${activeOrigin.alt}`;

  const [localGPS, setLocalGPS] = useState<LocalGPS>({ lat: 0, lon: 0, alt: 0, accuracy: 999 });

  useEffect(() => {
    if (!isMobile) return;
    if (!navigator.geolocation) return;

    const id = navigator.geolocation.watchPosition(
      (pos) => {
        setLocalGPS({
          lat: pos.coords.latitude,
          lon: pos.coords.longitude,
          alt: pos.coords.altitude ?? 0,
          accuracy: pos.coords.accuracy,
        });
      },
      (err) => console.warn('GPS 錯誤:', err),
      { enableHighAccuracy: true, maximumAge: 1000 }
    );
    return () => navigator.geolocation.clearWatch(id);
  }, [isMobile]);

  // ── GPS Sync ────────────────────────────────────────────────────
  const {
    myDeviceId,
    deviceName,
    updateDeviceName,
    allDevices,
    clearPathTrigger,
    sendClearPath,
    photoEvent,
    photoDeleteEvent,
    connectionStatus,
  } = useGPSSync(localGPS);

  // ── 選定追蹤的裝置（電腦端）──────────────────────────────────────
  const [selectedDeviceId, setSelectedDeviceId] = useState<string | null>(null);
  const aircraftEntry = useMemo(() => {
    const entries = [...allDevices.entries()];
    return (
      entries.find(([id, d]) => d.deviceType === 'uav' || id.includes('m4p') || id.includes('align')) ??
      null
    );
  }, [allDevices]);
  // 當第一個裝置上線時自動選取
  useEffect(() => {
    if (selectedDeviceId && allDevices.has(selectedDeviceId)) return;
    const first = aircraftEntry?.[0] ?? allDevices.keys().next().value;
    if (first) setSelectedDeviceId(first);
  }, [aircraftEntry, allDevices, selectedDeviceId]);

  // ── UAV 位置 + 軌跡 ──────────────────────────────────────────────
  const [uavPosition, setUavPosition] = useState<[number, number, number]>(() => getInitialRxPosition());
  const [uavPath, setUavPath] = useState<Array<{ x: number; y: number; z: number }>>([]);

  // ── 同步 UAV 位置 → DeviceStore rx（讓 ISS/SINR 模擬使用即時座標）────
  const updateDevice = useDeviceStore(s => s.updateDevice);
  useEffect(() => {
    updateDevice('dev-rx-0', { x: uavPosition[0], y: uavPosition[1], z: uavPosition[2] });
  }, [uavPosition, updateDevice]); 

  // ── 所有裝置的軌跡（每台一架無人機）────────────────────────────────
  const allDevicePathsRef = useRef<Map<string, { position: [number, number, number]; path: Array<{ x: number; y: number; z: number }> }>>(new Map());
  const [otherUavs, setOtherUavs] = useState<Array<{ id: string; position: [number, number, number]; path: Array<{ x: number; y: number; z: number }> }>>([]);

  useEffect(() => {
    const trackId = isMobile ? myDeviceId : selectedDeviceId;
    if (!trackId) return;

    // 手機端追自己、電腦端追選定的裝置
    const gps = isMobile
      ? (localGPS.lat !== 0 ? localGPS : null)
      : allDevices.get(trackId ?? '') ?? null;

    if (!gps) return;

    const [ex, ez, ealt] = latLonToENU(gps.lat, gps.lon, gps.alt, activeOrigin);
    const x = ex * SCALE;
    const z = ez * SCALE;
    const y = Math.max(ealt * ALT_GAIN, 10);

    setUavPosition([x, y, z]);
    setUavPath(prev => {
      const last = prev[prev.length - 1];
      if (last && Math.abs(last.x - x) < 0.1 && Math.abs(last.z - z) < 0.1) return prev;
      return [...prev, { x, y, z }];
    });
  }, [activeOrigin, allDevices, localGPS, selectedDeviceId, myDeviceId, isMobile]);

  // ── 追蹤所有裝置位置、建立各自軌跡 ─────────────────────────────────
  useEffect(() => {
    const pmap = allDevicePathsRef.current;
    // 移除已斷線的裝置
    pmap.forEach((_, id) => { if (!allDevices.has(id)) pmap.delete(id); });

    allDevices.forEach((gps, deviceId) => {
      const [ex, ez, ealt] = latLonToENU(gps.lat, gps.lon, gps.alt, activeOrigin);
      const x = ex * SCALE;
      const z = ez * SCALE;
      const y = Math.max(ealt * ALT_GAIN, 10);
      const newPos: [number, number, number] = [x, y, z];
      const existing = pmap.get(deviceId);
      let path: Array<{ x: number; y: number; z: number }>;
      if (existing) {
        const last = existing.path[existing.path.length - 1];
        path = (last && Math.abs(last.x - x) < 0.1 && Math.abs(last.z - z) < 0.1)
          ? existing.path
          : [...existing.path, { x, y, z }];
      } else {
        path = [{ x, y, z }];
      }
      pmap.set(deviceId, { position: newPos, path });
    });

    // 除了 selectedDevice 以外，全部作為「其他無人機」
    const others: Array<{ id: string; position: [number, number, number]; path: Array<{ x: number; y: number; z: number }> }> = [];
    pmap.forEach((data, id) => {
      if (isMobile || id !== selectedDeviceId) {
        others.push({ id, position: data.position, path: data.path });
      }
    });
    setOtherUavs(others);
  }, [activeOrigin, allDevices, selectedDeviceId, isMobile]);

  // ── 清除軌跡 ─────────────────────────────────────────────────────
  useEffect(() => {
    if (clearPathTrigger > 0) {
      setUavPath([]);
      allDevicePathsRef.current.forEach((data, id) => {
        allDevicePathsRef.current.set(id, { position: data.position, path: [] });
      });
      setOtherUavs(prev => prev.map(u => ({ ...u, path: [] })));
    }
  }, [clearPathTrigger]);

  // 切換場景時重置 UAV 路徑（ENU 原點改變，舊路徑座標無效）
  useEffect(() => {
    setUavPath([]);
    allDevicePathsRef.current.forEach((data, id) => {
      allDevicePathsRef.current.set(id, { position: data.position, path: [] });
    });
    setOtherUavs(prev => prev.map(u => ({ ...u, path: [] })));
  }, [activeOriginKey]);

  useEffect(() => {
    if (selectedScene.source !== 'generated') return;
    if (!activeGeneratedScene) {
      setSelectedScene({ source: 'preset', id: lastPresetSceneId });
    }
  }, [activeGeneratedScene?.taskId, lastPresetSceneId, selectedScene.source]);

  const handleClearPath = useCallback(() => {
    sendClearPath();
    setUavPath([]);
  }, [sendClearPath]);

  // ── 照片管理 ─────────────────────────────────────────────────────
  const [photos, setPhotos] = useState<Photo[]>([]);

  // 初始載入
  useEffect(() => {
    fetch(`${API}/api/photo-history`)
      .then(r => r.json())
      .then(d => { if (d.success) setPhotos(d.photos); })
      .catch(() => {});
  }, []);

  // WebSocket 新照片
  useEffect(() => {
    if (!photoEvent) return;
    setPhotos(prev => {
      if (prev.some(p => p.filename === photoEvent.filename)) return prev;
      return [photoEvent as unknown as Photo, ...prev];
    });
  }, [photoEvent]);

  // WebSocket 刪除照片
  useEffect(() => {
    if (!photoDeleteEvent) return;
    setPhotos(prev => prev.filter(p => p.filename !== photoDeleteEvent.filename));
  }, [photoDeleteEvent]);

  const handleDelete = useCallback((filename: string) => {
    setPhotos(prev => prev.filter(p => p.filename !== filename));
  }, []);

  // ── 改名 ─────────────────────────────────────────────────────────
  const handleRename = useCallback(() => {
    const name = prompt('輸入新的裝置名稱', deviceName);
    if (name && name.trim()) updateDeviceName(name.trim());
  }, [deviceName, updateDeviceName]);

  // ── 目前 GPS（供 HUD 顯示）────────────────────────────────────────
  const currentGPS = isMobile && localGPS.lat !== 0 ? localGPS : null;
  const simulationSceneId = activeGeneratedScene?.sceneKey ?? renderSceneId;
  const simulationUsesGeneratedScene = Boolean(activeGeneratedScene);
  const [cfarClusters, setCfarClusters] = useState<CFARCluster[]>([]);
  const [heatmapOverlay, setHeatmapOverlay] = useState<HeatmapOverlayConfig | null>(null);
  const cfarBeacons = useMemo<CFARBeacon[]>(() => (
    cfarClusters.map((cluster) => {
      const gps = worldXZToLatLon(cluster.world_x, cluster.world_z, activeOrigin);
      return {
        ...cluster,
        lat: isFiniteNumber(cluster.lat) ? cluster.lat : gps.lat,
        lon: isFiniteNumber(cluster.lon) ? cluster.lon : gps.lon,
        alt: gps.alt,
      };
    })
  ), [activeOrigin, cfarClusters]);

  useEffect(() => {
    setCfarClusters([]);
    setHeatmapOverlay(null);
  }, [activeOriginKey, simulationSceneId]);

  // ── Render ────────────────────────────────────────────────────────
  return (
    <div style={{ width: '100vw', height: '100dvh', position: 'relative' }}>

      {/* 3D 場景 */}
      <MainScene
        uavPosition={uavPosition}
        uavPath={uavPath}
        sceneId={renderSceneId}
        auto={auto}
        manualDirection={manualDirection}
        onManualMoveDone={handleManualMoveDone}
        uavAnimation={uavAnimation}
        otherUavs={otherUavs}
        cfarBeacons={cfarBeacons}
        heatmapOverlay={heatmapOverlay}
        generatedSceneModelPath={activeGeneratedScene?.modelPath}
        onPositionUpdate={(pos) => {
          setUavPosition(pos);
          setUavPath(prev => {
            const last = prev[prev.length - 1];
            if (last && Math.abs(last.x - pos[0]) < 0.1 && Math.abs(last.z - pos[2]) < 0.1) return prev;
            return [...prev, { x: pos[0], y: pos[1], z: pos[2] }];
          });
        }}
      />

      {/* Device Configuration 面板 (加入 sim-world-lite 的裝置設定) */}
      {!isMobile && (
        <DevicePanel onApplyRxPosition={(pos) => setUavPosition(pos)} />
      )}

      {/* UAV Control 面板 (手動控制/自動移動) */}
      {!isMobile && (
        <UAVControlPanel
          auto={auto}
          uavAnimation={uavAnimation}
          uavPosition={uavPosition}
          onToggleAuto={handleToggleAuto}
          onToggleAnimation={() => setUavAnimation(prev => !prev)}
          onManualControl={handleManualControl}
        />
      )}

      {/* GPS 狀態 HUD */}
      <AircraftTelemetry
        deviceId={aircraftEntry?.[0] ?? null}
        device={aircraftEntry?.[1] ?? null}
        isTracked={Boolean(aircraftEntry && selectedDeviceId === aircraftEntry[0])}
        compact={isMobile}
        onTrack={() => {
          if (aircraftEntry) setSelectedDeviceId(aircraftEntry[0]);
        }}
      />
      {!isMobile && (
        <USRPTelemetry />
      )}

      <GPSStatus
        myDeviceId={myDeviceId}
        deviceName={deviceName}
        onRenameClick={handleRename}
        allDevices={allDevices}
        uavPath={uavPath}
        onClearPath={handleClearPath}
        connectionStatus={connectionStatus}
        localGPS={currentGPS}
        selectedDeviceId={selectedDeviceId}
        onSelectDevice={setSelectedDeviceId}
      />

      {/* 照片歷史（電腦端） */}
      {!isMobile && (
        <PhotoViewer photos={photos} onDelete={handleDelete} />
      )}

      {/* 拍照上傳（手機端） */}
      <CameraUpload
        currentPosition={currentGPS ? { lat: currentGPS.lat, lon: currentGPS.lon, altitude: currentGPS.alt } : null}
        deviceId={myDeviceId}
      />

      {/* Sionna 無線模擬面板（電腦端） */}
      {!isMobile && (
        <SimulationPanel
          sceneId={simulationSceneId}
          generatedScene={simulationUsesGeneratedScene}
          onCfarClustersChange={setCfarClusters}
          onHeatmapOverlayChange={setHeatmapOverlay}
        />
      )}

      {/* 場景切換器 */}
      {!isMobile && <ControllerScreenPanel />}

      {!isMobile && (
        <SceneSwitcher
          selectedScene={selectedScene}
          generatedScenes={generatedScenes.scenes}
          generatedStatus={generatedScenes.status}
          onSelectPreset={(id) => {
            setLastPresetSceneId(id);
            setSelectedScene({ source: 'preset', id });
          }}
          onSelectGenerated={(taskId) => {
            setSelectedScene({ source: 'generated', taskId });
          }}
        />
      )}
    </div>
  );
}
