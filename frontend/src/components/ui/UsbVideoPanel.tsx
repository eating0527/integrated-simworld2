import { useEffect, useRef, useState } from 'react';

interface VideoDeviceInfo {
  deviceId: string;
  label: string;
}

const PREFERRED_LABELS = ['uvc', 'webcam', 'camera', 'usb'];

function rankDevice(device: MediaDeviceInfo): number {
  const label = device.label.toLowerCase();
  const idx = PREFERRED_LABELS.findIndex((keyword) => label.includes(keyword));
  return idx === -1 ? PREFERRED_LABELS.length : idx;
}

export function UsbVideoPanel() {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const [devices, setDevices] = useState<VideoDeviceInfo[]>([]);
  const [selectedDeviceId, setSelectedDeviceId] = useState('');
  const [error, setError] = useState('');
  const [isStarting, setIsStarting] = useState(false);
  const [isReady, setIsReady] = useState(false);

  const stopStream = () => {
    const stream = streamRef.current;
    if (stream) {
      stream.getTracks().forEach((track) => track.stop());
      streamRef.current = null;
    }
    if (videoRef.current) {
      videoRef.current.srcObject = null;
    }
    setIsReady(false);
  };

  const loadDevices = async () => {
    const allDevices = await navigator.mediaDevices.enumerateDevices();
    const videoInputs = allDevices
      .filter((device) => device.kind === 'videoinput')
      .sort((a, b) => rankDevice(a) - rankDevice(b))
      .map((device, index) => ({
        deviceId: device.deviceId,
        label: device.label || `Camera ${index + 1}`,
      }));

    setDevices(videoInputs);
    setSelectedDeviceId((current) => {
      if (current && videoInputs.some((device) => device.deviceId === current)) {
        return current;
      }
      return videoInputs[0]?.deviceId ?? '';
    });
    return videoInputs;
  };

  const startStream = async (deviceId?: string) => {
    if (!navigator.mediaDevices?.getUserMedia) {
      setError('Browser does not support live camera capture.');
      return;
    }

    setIsStarting(true);
    setError('');
    stopStream();

    try {
      const constraints: MediaStreamConstraints = {
        video: deviceId
          ? {
              deviceId: { exact: deviceId },
              width: { ideal: 1280 },
              height: { ideal: 720 },
              frameRate: { ideal: 30, max: 60 },
            }
          : {
              width: { ideal: 1280 },
              height: { ideal: 720 },
              frameRate: { ideal: 30, max: 60 },
            },
        audio: false,
      };
      const stream = await navigator.mediaDevices.getUserMedia(constraints);
      streamRef.current = stream;

      if (videoRef.current) {
        videoRef.current.srcObject = stream;
        await videoRef.current.play().catch(() => undefined);
      }

      const loadedDevices = await loadDevices();
      const activeTrack = stream.getVideoTracks()[0];
      const activeDeviceId = activeTrack?.getSettings().deviceId;
      if (activeDeviceId && loadedDevices.some((device) => device.deviceId === activeDeviceId)) {
        setSelectedDeviceId(activeDeviceId);
      }
      setIsReady(true);
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Unable to open USB camera.';
      setError(message);
      setIsReady(false);
    } finally {
      setIsStarting(false);
    }
  };

  useEffect(() => {
    let cancelled = false;

    const init = async () => {
      if (!navigator.mediaDevices?.enumerateDevices) {
        setError('Browser cannot enumerate local cameras.');
        return;
      }

      try {
        const videoInputs = await loadDevices();
        if (!cancelled && videoInputs.length > 0) {
          await startStream(videoInputs[0].deviceId);
        } else if (!cancelled) {
          setError('No video input devices detected.');
        }
      } catch (err) {
        const message = err instanceof Error ? err.message : 'Unable to enumerate USB cameras.';
        if (!cancelled) setError(message);
      }
    };

    void init();

    const handleDeviceChange = () => {
      void loadDevices();
    };
    navigator.mediaDevices?.addEventListener?.('devicechange', handleDeviceChange);

    return () => {
      cancelled = true;
      navigator.mediaDevices?.removeEventListener?.('devicechange', handleDeviceChange);
      stopStream();
    };
  }, []);

  return (
    <div className="usb-video-panel">
      <div className="usb-video-panel__header">
        <div>
          <div className="usb-video-panel__eyebrow">Live Video</div>
          <div className="usb-video-panel__title">USB Camera</div>
        </div>
        <div className={`usb-video-panel__status ${isReady ? 'is-live' : ''}`}>
          {isStarting ? 'Connecting' : isReady ? 'Live' : 'Idle'}
        </div>
      </div>

      <div className="usb-video-panel__frame">
        <video
          ref={videoRef}
          className="usb-video-panel__video"
          autoPlay
          muted
          playsInline
        />
        {!isReady && (
          <div className="usb-video-panel__empty">
            <div>{isStarting ? 'Opening camera feed...' : 'Camera feed unavailable'}</div>
            {error && <div className="usb-video-panel__error">{error}</div>}
          </div>
        )}
      </div>

      <div className="usb-video-panel__controls">
        <select
          className="usb-video-panel__select"
          value={selectedDeviceId}
          onChange={(e) => {
            const nextDeviceId = e.target.value;
            setSelectedDeviceId(nextDeviceId);
            void startStream(nextDeviceId);
          }}
          disabled={devices.length === 0 || isStarting}
        >
          {devices.map((device) => (
            <option key={device.deviceId} value={device.deviceId}>
              {device.label}
            </option>
          ))}
        </select>
        <button
          type="button"
          className="usb-video-panel__button"
          onClick={() => void startStream(selectedDeviceId)}
          disabled={isStarting || (!selectedDeviceId && devices.length === 0)}
        >
          Refresh
        </button>
      </div>
    </div>
  );
}
