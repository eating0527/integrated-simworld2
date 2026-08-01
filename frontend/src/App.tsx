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
import { enuToGrid, enuToThree, gpsToEnu } from './utils/geo';
import { ControllerScreenPanel } from './components/ui/ControllerScreenPanel';
import { SimulationPanel } from './components/ui/SimulationPanel';
import { SceneSwitcher, type SelectedScene } from './components/ui/SceneSwitcher';
import { type SceneId, DEFAULT_SCENE_ID, getSceneById } from './config/scenes.config';
import { DevicePanel } from './components/ui/DevicePanel';
import { UAVControlPanel } from './components/ui/UAVControlPanel';
import { AircraftTelemetry } from './components/ui/AircraftTelemetry';
import { USRPTelemetry } from './components/ui/USRPTelemetry';
import { Workspace } from './components/ui/Workspace';
import { TrajectoryHistoryPanel, type TrajectoryEvent } from './components/ui/TrajectoryHistoryPanel';
import { useManualControl } from './hooks/useManualControl';
import { useDeviceStore } from './store/useDeviceStore';
import type { CFARBeacon, CFARCluster } from './types/cfar';
import type { HeatmapOverlayConfig, ISSRouteOverlayConfig } from './types/heatmap';
import { createSceneFrame, type SceneFrame } from './types/sceneFrame';
import {
  getGpsReplayIntervalMs,
  parseGpsReplayCsv,
  type GpsReplayPoint,
  type GpsReplayRate,
} from './utils/gpsReplay';

// ── 環境變數 ────────────────────────────────────────────────────────

// 空字串時使用相對路徑，讓 Vite proxy 接管（本地開發用）
const API = import.meta.env.VITE_API_URL || '';


// ── Types ───────────────────────────────────────────────────────────
interface LocalGPS {
  lat: number;
  lon: number;
  alt: number;
  accuracy: number;
  alt_mode: 'amsl' | 'relative';
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

function getInitialRxPosition(): [number, number, number] {
  const rx = useDeviceStore.getState().devices.find((d) => d.id === 'dev-rx-0');
  return rx ? [rx.x, rx.y, rx.z] : [0, 0, 0];
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

// ── App ─────────────────────────────────────────────────────────────
export function App() {
  const isMobile = /iPhone|iPad|iPod|Android/i.test(navigator.userAgent);

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
  const defaultFrame = useMemo(() => createSceneFrame(`scene-${renderSceneId}`, {
    lat: sceneDef.config.observer.lat,
    lon: sceneDef.config.observer.lon,
    alt_m: sceneDef.config.observer.alt,
  }), [
    renderSceneId,
    sceneDef.config.observer.alt,
    sceneDef.config.observer.lat,
    sceneDef.config.observer.lon,
  ]);
  const activeFrame = useMemo<SceneFrame>(() => {
    if (activeGeneratedScene?.frame) return activeGeneratedScene.frame;
    const location = activeGeneratedScene?.location;
    if (location && isFiniteNumber(location.lat) && isFiniteNumber(location.lon)) {
      return createSceneFrame(`scene-${activeGeneratedScene.sceneKey}`, {
        lat: location.lat,
        lon: location.lon,
        alt_m: 0,
      });
    }
    return defaultFrame;
  }, [activeGeneratedScene, defaultFrame]);
  const activeOriginKey = activeFrame.frame_id;

  const [localGPS, setLocalGPS] = useState<LocalGPS>({ lat: 0, lon: 0, alt: 0, accuracy: 999, alt_mode: 'amsl' });
  const [activeStatusPanel, setActiveStatusPanel] = useState<'gps' | 'connection' | null>(null);

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
          alt_mode: 'amsl',
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
  const [gpsReplayPoints, setGpsReplayPoints] = useState<GpsReplayPoint[]>([]);
  const [gpsReplayIndex, setGpsReplayIndex] = useState(0);
  const [gpsReplayPlaying, setGpsReplayPlaying] = useState(false);
  const [gpsReplayRate, setGpsReplayRate] = useState<GpsReplayRate>(1);

  // ── 同步 UAV 位置 → DeviceStore rx（讓 ISS/SINR 模擬使用即時座標）────
  const updateDevice = useDeviceStore(s => s.updateDevice);
  useEffect(() => {
    updateDevice('dev-rx-0', { x: uavPosition[0], y: uavPosition[1], z: uavPosition[2] });
  }, [uavPosition, updateDevice]); 

  // ── 所有裝置的軌跡（每台一架無人機）────────────────────────────────
  const allDevicePathsRef = useRef<Map<string, { position: [number, number, number]; path: Array<{ x: number; y: number; z: number }> }>>(new Map());
  const [otherUavs, setOtherUavs] = useState<Array<{ id: string; position: [number, number, number]; path: Array<{ x: number; y: number; z: number }> }>>([]);

  useEffect(() => {
    if (gpsReplayPoints.length > 0) return;
    const trackId = isMobile ? myDeviceId : selectedDeviceId;
    if (!trackId) return;

    // 手機端追自己、電腦端追選定的裝置
    const gps = isMobile
      ? (localGPS.lat !== 0 ? localGPS : null)
      : allDevices.get(trackId ?? '') ?? null;

    if (!gps) return;

    const [x, y, z] = enuToThree(gpsToEnu(gps, activeFrame, gps.alt_mode));

    setUavPosition([x, y, z]);
    setUavPath(prev => {
      const last = prev[prev.length - 1];
      if (last && Math.abs(last.x - x) < 0.1 && Math.abs(last.y - y) < 0.1 && Math.abs(last.z - z) < 0.1) return prev;
      return [...prev, { x, y, z }];
    });
  }, [activeFrame, allDevices, gpsReplayPoints.length, localGPS, selectedDeviceId, myDeviceId, isMobile]);

  const applyGpsReplayPoint = useCallback((point: GpsReplayPoint) => {
    const enu = gpsToEnu(point, activeFrame, point.altMode);
    if (!enuToGrid(enu, activeFrame).displayable) return;
    const pos = enuToThree(enu);
    setUavPosition(pos);
    setUavPath(prev => {
      const last = prev[prev.length - 1];
      if (last && Math.abs(last.x - pos[0]) < 0.1 && Math.abs(last.y - pos[1]) < 0.1 && Math.abs(last.z - pos[2]) < 0.1) return prev;
      return [...prev, { x: pos[0], y: pos[1], z: pos[2] }];
    });
  }, [activeFrame]);

  const handleGpsReplayPlay = useCallback(async (file: File) => {
    if (gpsReplayPoints.length > 0 && gpsReplayIndex > 0) {
      setGpsReplayPlaying(true);
      return;
    }

    const points = parseGpsReplayCsv(await file.text());
    if (points.length === 0) {
      window.alert('GPS CSV 沒有可回播的座標點');
      return;
    }

    setAuto(false);
    resetManualControl();
    setUavPath([]);
    applyGpsReplayPoint(points[0]);
    setGpsReplayPoints(points);
    setGpsReplayIndex(1);
    setGpsReplayPlaying(points.length > 1);
  }, [applyGpsReplayPoint, gpsReplayIndex, gpsReplayPoints.length, resetManualControl]);

  const handleGpsReplayPause = useCallback(() => {
    setGpsReplayPlaying(false);
  }, []);

  const handleGpsReplayStop = useCallback(() => {
    setGpsReplayPlaying(false);
    setGpsReplayPoints([]);
    setGpsReplayIndex(0);
  }, []);

  useEffect(() => {
    if (!gpsReplayPlaying || gpsReplayPoints.length === 0) return;

    const timer = window.setInterval(() => {
      setGpsReplayIndex(prev => {
        const point = gpsReplayPoints[prev];
        if (!point) {
          setGpsReplayPlaying(false);
          return prev;
        }

        applyGpsReplayPoint(point);
        const next = prev + 1;
        if (next >= gpsReplayPoints.length) {
          setGpsReplayPlaying(false);
        }
        return next;
      });
    }, getGpsReplayIntervalMs(gpsReplayRate));

    return () => window.clearInterval(timer);
  }, [applyGpsReplayPoint, gpsReplayPlaying, gpsReplayPoints, gpsReplayRate]);

  // ── 追蹤所有裝置位置、建立各自軌跡 ─────────────────────────────────
  useEffect(() => {
    const pmap = allDevicePathsRef.current;
    // 移除已斷線的裝置
    pmap.forEach((_, id) => { if (!allDevices.has(id)) pmap.delete(id); });

    allDevices.forEach((gps, deviceId) => {
      const newPos = enuToThree(gpsToEnu(gps, activeFrame, gps.alt_mode));
      const [x, y, z] = newPos;
      const existing = pmap.get(deviceId);
      let path: Array<{ x: number; y: number; z: number }>;
      if (existing) {
        const last = existing.path[existing.path.length - 1];
        path = (last && Math.abs(last.x - x) < 0.1 && Math.abs(last.y - y) < 0.1 && Math.abs(last.z - z) < 0.1)
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
  }, [activeFrame, allDevices, selectedDeviceId, isMobile]);

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
  const [issRouteOverlay, setIssRouteOverlay] = useState<ISSRouteOverlayConfig | null>(null);
  const [selectedTrajectoryEvent, setSelectedTrajectoryEvent] = useState<TrajectoryEvent | null>(null);
  const cfarBeacons = useMemo<CFARBeacon[]>(
    () => cfarClusters.filter((cluster) => cluster.grid.displayable),
    [cfarClusters],
  );


  useEffect(() => {
    setCfarClusters([]);
    setHeatmapOverlay(null);
    setIssRouteOverlay(null);
  }, [activeOriginKey, simulationSceneId]);

  const historicalPaths = useMemo(() => {
    if (!selectedTrajectoryEvent) return [];
    const colors = ['#f59e0b', '#38bdf8', '#f472b6', '#a3e635', '#c084fc', '#fb7185'];
    return selectedTrajectoryEvent.devices
      .map((device, index) => {
        const path = device.points
          .map((point) => {
            if (!isFiniteNumber(point.lat) || !isFiniteNumber(point.lon)) return null;
            const alt = point.alt ?? (activeFrame.alt_mode === 'amsl' ? activeFrame.origin.alt_m : 0);
            const enu = gpsToEnu({ lat: point.lat, lon: point.lon, alt }, activeFrame);
            if (!enuToGrid(enu, activeFrame).displayable) return null;
            const [x, y, z] = enuToThree(enu);
            return { x, y, z };
          })
          .filter((point): point is { x: number; y: number; z: number } => Boolean(point));
        return {
          id: `${selectedTrajectoryEvent.id}:${device.deviceId}`,
          label: device.deviceName || device.deviceId,
          color: colors[index % colors.length],
          path,
        };
      })
      .filter(track => track.path.length >= 2);
  }, [activeFrame, selectedTrajectoryEvent]);

  const aircraftPanel = (
    <AircraftTelemetry
      deviceId={aircraftEntry?.[0] ?? null}
      device={aircraftEntry?.[1] ?? null}
      isTracked={Boolean(aircraftEntry && selectedDeviceId === aircraftEntry[0])}
      compact={isMobile}
      statusBar={!isMobile}
      minimized={!isMobile ? activeStatusPanel !== 'gps' : undefined}
      onMinimizedChange={!isMobile ? (minimized) => setActiveStatusPanel(minimized ? null : 'gps') : undefined}
      onTrack={() => {
        if (aircraftEntry) setSelectedDeviceId(aircraftEntry[0]);
      }}
    />
  );
  const gpsPanel = (
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
      statusBar={!isMobile}
      minimized={!isMobile ? activeStatusPanel !== 'connection' : undefined}
      onMinimizedChange={!isMobile ? (minimized) => setActiveStatusPanel(minimized ? null : 'connection') : undefined}
    />
  );

  // ── Render ────────────────────────────────────────────────────────
  return (
    <Workspace
      top={!isMobile && (
        <div className="workspace__statusbar" aria-label="即時狀態列">
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
            onRenameGenerated={generatedScenes.renameScene}
            onDeleteGenerated={generatedScenes.deleteScene}
          />
          <div className="workspace__statusbar-items">
            {aircraftPanel}
            {gpsPanel}
          </div>
        </div>
      )}
      left={!isMobile && (
        <>
          <DevicePanel sceneFrame={activeFrame} onApplyRxPosition={(pos) => setUavPosition(pos)} />
          <UAVControlPanel
            auto={auto}
            uavAnimation={uavAnimation}
            uavPosition={uavPosition}
            onToggleAuto={handleToggleAuto}
            onToggleAnimation={() => setUavAnimation(prev => !prev)}
            onManualControl={handleManualControl}
          />
          <USRPTelemetry sceneId={simulationSceneId} />
        </>
      )}
      right={!isMobile && (
        <>
          <ControllerScreenPanel />
          <SimulationPanel
            sceneId={simulationSceneId}
            generatedScene={simulationUsesGeneratedScene}
            sceneFrame={activeFrame}
            onCfarClustersChange={setCfarClusters}
            onHeatmapOverlayChange={setHeatmapOverlay}
            onRouteOverlayChange={setIssRouteOverlay}
            gpsReplayRate={gpsReplayRate}
            gpsReplayPlaying={gpsReplayPlaying}
            onGpsReplayPlay={handleGpsReplayPlay}
            onGpsReplayPause={handleGpsReplayPause}
            onGpsReplayStop={handleGpsReplayStop}
            onGpsReplayRateChange={setGpsReplayRate}
          />
          <TrajectoryHistoryPanel
            selectedEventId={selectedTrajectoryEvent?.id ?? null}
            onSelectEvent={setSelectedTrajectoryEvent}
          />
          <PhotoViewer photos={photos} onDelete={handleDelete} />
        </>
      )}
    >

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
        historicalPaths={historicalPaths}
        cfarBeacons={cfarBeacons}
        heatmapOverlay={heatmapOverlay}
        issRouteOverlay={issRouteOverlay}
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

      {isMobile && aircraftPanel}
      {isMobile && gpsPanel}

      {/* 拍照上傳（手機端） */}
      <CameraUpload
        currentPosition={currentGPS ? { lat: currentGPS.lat, lon: currentGPS.lon, altitude: currentGPS.alt } : null}
        deviceId={myDeviceId}
      />

    </Workspace>
  );
}
