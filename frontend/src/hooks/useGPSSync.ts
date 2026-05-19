/**
 * useGPSSync — GPS 多裝置同步 Hook
 *
 * 負責：
 * 1. 取得本機 GPS（手機端）並透過 WebSocket 廣播
 * 2. 接收其他裝置的 GPS 資料（電腦端顯示）
 * 3. 接收照片上傳 / 刪除事件
 * 4. 發送 / 接收清除軌跡指令
 */
import { useEffect, useState, useRef, useCallback } from 'react';
import { useWebSocket } from './useWebSocket';

// ────────────────────────────── Types ──────────────────────────────

export interface GPSDevice {
  lat: number;
  lon: number;
  alt: number;
  accuracy: number;
  deviceId: string;
  deviceName: string;
  deviceType: 'mobile' | 'desktop' | 'uav' | 'unknown';
  timestamp: number;
  lastUpdateTime: number;
}

export interface PhotoEvent {
  type: 'photo-upload';
  filename: string;
  url: string;
  timestamp: string;
  latitude?: number | null;
  longitude?: number | null;
  altitude?: number | null;
  deviceId?: string | null;
}

export interface PhotoDeleteEvent {
  type: 'photo_deleted';
  filename: string;
  timestamp: string;
}

export interface USRPSpectrumEvent {
  type: 'usrp-spectrum';
  deviceId: string;
  deviceName: string;
  deviceType: 'mobile' | 'desktop' | 'uav' | 'unknown' | string;
  timestamp: number;
  lat?: number | null;
  lon?: number | null;
  alt?: number | null;
  accuracy?: number | null;
  center_freq_hz: number;
  sample_rate_hz: number;
  gain_db: number;
  bandwidth_hz?: number;
  channel: number;
  sample_count: number;
  capture_seconds: number;
  mean_power_dbfs: number;
  peak_power_dbfs: number;
  rms_dbfs: number;
  max_iq_abs: number;
}

export interface GPSSyncResult {
  myDeviceId: string;
  deviceName: string;
  updateDeviceName: (name: string) => void;
  allDevices: Map<string, GPSDevice>;
  clearPathTrigger: number;
  sendClearPath: () => void;
  photoEvent: PhotoEvent | null;
  photoDeleteEvent: PhotoDeleteEvent | null;
  usrpSpectrumByDevice: Map<string, USRPSpectrumEvent>;
  connectionStatus: 'connecting' | 'connected' | 'disconnected' | 'failed';
}

// ────────────────────────────── Helpers ────────────────────────────

function getSessionId(): string {
  const key = 'gps-tracker-session-id';
  let id = sessionStorage.getItem(key);
  if (!id) {
    id = `device-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
    sessionStorage.setItem(key, id);
  }
  return id;
}

function getDeviceName(): string {
  const key = 'gps-tracker-device-name';
  let name = localStorage.getItem(key);
  if (!name) {
    const isMobile = /iPhone|iPad|iPod|Android/i.test(navigator.userAgent);
    name = `${isMobile ? '📱 手機' : '💻 電腦'}_${Math.floor(Math.random() * 1000)}`;
    localStorage.setItem(key, name);
  }
  return name;
}

function hasMoved(
  prev: { lat: number; lon: number; alt: number },
  curr: { lat: number; lon: number; alt: number }
): boolean {
  return (
    Math.abs(prev.lat - curr.lat) > 0.000001 ||
    Math.abs(prev.lon - curr.lon) > 0.000001 ||
    Math.abs(prev.alt - curr.alt) > 0.1
  );
}

// ────────────────────────────── Hook ───────────────────────────────

export function useGPSSync(
  localGPS: { lat: number; lon: number; alt: number; accuracy: number }
): GPSSyncResult {
  const [myDeviceId] = useState(getSessionId);
  const [deviceName, setDeviceName] = useState(getDeviceName);
  const [allDevices, setAllDevices] = useState<Map<string, GPSDevice>>(new Map());
  const [clearPathTrigger, setClearPathTrigger] = useState(0);
  const [photoEvent, setPhotoEvent] = useState<PhotoEvent | null>(null);
  const [photoDeleteEvent, setPhotoDeleteEvent] = useState<PhotoDeleteEvent | null>(null);
  const [usrpSpectrumByDevice, setUsrpSpectrumByDevice] = useState<Map<string, USRPSpectrumEvent>>(new Map());

  const isMobile = /iPhone|iPad|iPod|Android/i.test(navigator.userAgent);
  const registeredRef = useRef(false);
  const lastSentRef = useRef({ lat: 0, lon: 0, alt: 0 });
  const lastSentTimeRef = useRef(0);
  const localGPSRef = useRef(localGPS);

  useEffect(() => { localGPSRef.current = localGPS; }, [localGPS]);

  // ── Handle incoming messages ──────────────────────────────────────
  const handleMessage = useCallback((event: MessageEvent) => {
    try {
      const msg = JSON.parse(event.data as string);
      const { type } = msg;

      // GPS data from another device
      if (msg.lat !== undefined && msg.lon !== undefined) {
        const incoming = msg as GPSDevice;
        if (incoming.deviceId === myDeviceId) return; // 自己的，跳過

        setAllDevices(prev => {
          const next = new Map(prev);
          next.set(incoming.deviceId, {
            ...incoming,
            lastUpdateTime: Date.now(),
          });
          return next;
        });
        return;
      }

      if (type === 'device-disconnected') {
        setAllDevices(prev => {
          const next = new Map(prev);
          next.delete(msg.deviceId);
          return next;
        });
        setUsrpSpectrumByDevice(prev => {
          const next = new Map(prev);
          next.delete(msg.deviceId);
          return next;
        });
        return;
      }

      if (type === 'clear-path') {
        // 只有不是自己發出的才觸發
        if (msg.deviceId !== myDeviceId) {
          setClearPathTrigger(n => n + 1);
        }
        return;
      }

      if (type === 'photo-upload') {
        setPhotoEvent({ ...msg });
        return;
      }

      if (type === 'photo_deleted') {
        setPhotoDeleteEvent({ ...msg });
        return;
      }

      if (type === 'usrp-spectrum') {
        const eventPayload = msg as USRPSpectrumEvent;
        setUsrpSpectrumByDevice(prev => {
          const next = new Map(prev);
          next.set(eventPayload.deviceId, eventPayload);
          return next;
        });
        return;
      }
    } catch (_) {
      // ignore parse errors
    }
  }, [myDeviceId]);

  const { isConnected, connectionStatus, sendMessage } = useWebSocket({ onMessage: handleMessage });

  // ── 連線後註冊裝置 ───────────────────────────────────────────────
  useEffect(() => {
    if (isConnected && !registeredRef.current) {
      registeredRef.current = true;
      sendMessage({
        type: 'register-device',
        deviceId: myDeviceId,
        deviceName: deviceName,
        deviceType: isMobile ? 'mobile' : 'desktop',
      });
    }
    if (!isConnected) {
      registeredRef.current = false;
    }
  }, [isConnected, myDeviceId, deviceName, isMobile, sendMessage]);

  // ── 定期發送 GPS（只在手機端且已有有效座標時） ───────────────────
  useEffect(() => {
    if (!isMobile) return; // 電腦只接收，不發送

    const timer = setInterval(() => {
      if (!isConnected) return;
      const gps = localGPSRef.current;
      if (gps.lat === 0 && gps.lon === 0) return;

      const now = Date.now();
      const moved = hasMoved(lastSentRef.current, gps);
      const elapsed = now - lastSentTimeRef.current;

      if (moved || elapsed > 5000) {
        lastSentRef.current = { lat: gps.lat, lon: gps.lon, alt: gps.alt };
        lastSentTimeRef.current = now;
        sendMessage({
          lat: gps.lat,
          lon: gps.lon,
          alt: gps.alt,
          accuracy: gps.accuracy,
          deviceId: myDeviceId,
          deviceType: 'mobile',
          timestamp: now / 1000,
        });
      }
    }, 1000);

    return () => clearInterval(timer);
  }, [isMobile, isConnected, myDeviceId, sendMessage]);

  // ── 清除過期裝置（30 秒無更新視為離線） ──────────────────────────
  useEffect(() => {
    const timer = setInterval(() => {
      const threshold = Date.now() - 30_000;
      setAllDevices(prev => {
        const stale = [...prev.entries()].filter(([, d]) => d.lastUpdateTime < threshold);
        if (!stale.length) return prev;
        const next = new Map(prev);
        stale.forEach(([id]) => next.delete(id));
        return next;
      });
    }, 10_000);
    return () => clearInterval(timer);
  }, []);

  // ── Wake lock（手機螢幕不關閉） ───────────────────────────────────
  useEffect(() => {
    if (!isMobile || !('wakeLock' in navigator)) return;
    let sentinel: WakeLockSentinel | null = null;
    const acquire = async () => {
      try { sentinel = await navigator.wakeLock.request('screen'); } catch (_) {}
    };
    acquire();
    const onVisibility = () => { if (document.visibilityState === 'visible') acquire(); };
    document.addEventListener('visibilitychange', onVisibility);
    return () => {
      document.removeEventListener('visibilitychange', onVisibility);
      sentinel?.release();
    };
  }, [isMobile]);

  const updateDeviceName = useCallback((name: string) => {
    setDeviceName(name);
    localStorage.setItem('gps-tracker-device-name', name);
    sendMessage({ type: 'update-device-name', deviceId: myDeviceId, deviceName: name });
  }, [myDeviceId, sendMessage]);

  const sendClearPath = useCallback(() => {
    sendMessage({ type: 'clear-path', deviceId: myDeviceId, timestamp: Date.now() / 1000 });
    setClearPathTrigger(n => n + 1); // 自己也清除
  }, [myDeviceId, sendMessage]);

  return {
    myDeviceId,
    deviceName,
    updateDeviceName,
    allDevices,
    clearPathTrigger,
    sendClearPath,
    photoEvent,
    photoDeleteEvent,
    usrpSpectrumByDevice,
    connectionStatus,
  };
}
