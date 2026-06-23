/**
 * CameraUpload — 手機拍照上傳（Glassmorphism FAB）
 */
import { useRef, useState } from 'react';

interface Props {
  currentPosition?: { lat: number; lon: number; altitude?: number | null } | null;
  deviceId?: string | null;
  onUploadSuccess?: (filename: string) => void;
}

const API = import.meta.env.VITE_API_URL ?? 'https://backend.simworld.website';

export function CameraUpload({ currentPosition, deviceId, onUploadSuccess }: Props) {
  const isMobile = /iPhone|iPad|iPod|Android/i.test(navigator.userAgent);
  const fileRef = useRef<HTMLInputElement>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const [status, setStatus] = useState('');
  const [statusType, setStatusType] = useState<'info' | 'success' | 'error'>('info');
  const [uploading, setUploading] = useState(false);

  if (!isMobile) return null;

  const handleCapture = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    setPreview(URL.createObjectURL(file));
    setUploading(true);
    setStatusType('info');
    setStatus('上傳中…');

    const form = new FormData();
    form.append('photo', file);
    if (currentPosition) {
      form.append('latitude', String(currentPosition.lat));
      form.append('longitude', String(currentPosition.lon));
      if (currentPosition.altitude != null)
        form.append('altitude', String(currentPosition.altitude));
    }
    if (deviceId) form.append('deviceId', deviceId);

    try {
      const res = await fetch(`${API}/api/upload-photo`, { method: 'POST', body: form });
      const data = await res.json();
      if (res.ok && data.success) {
        setStatusType('success');
        setStatus('上傳成功');
        onUploadSuccess?.(data.filename);
      } else {
        setStatusType('error');
        setStatus(data.error ?? '上傳失敗');
      }
    } catch {
      setStatusType('error');
      setStatus('網路錯誤');
    } finally {
      setUploading(false);
      setTimeout(() => { setStatus(''); setPreview(null); }, 3000);
      if (fileRef.current) fileRef.current.value = '';
    }
  };

  const statusColors: Record<string, string> = {
    info:    'rgba(0,212,255,0.85)',
    success: 'rgba(0,255,136,0.85)',
    error:   'rgba(255,77,106,0.85)',
  };

  return (
    <div style={{
      position: 'fixed', bottom: 28, right: 20, zIndex: 1001,
      display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 12,
    }}>
      {/* 照片預覽卡片 */}
      {preview && (
        <div style={{
          background: 'rgba(8,12,28,0.85)',
          backdropFilter: 'blur(16px)',
          borderRadius: 'var(--panel-radius)',
          padding: 6,
          border: '1px solid rgba(0,255,136,0.3)',
          boxShadow: '0 0 20px rgba(0,255,136,0.2), 0 8px 24px rgba(0,0,0,0.5)',
          animation: 'fade-in 0.25s ease',
        }}>
          <img
            src={preview}
            alt="preview"
            style={{ width: 110, height: 110, objectFit: 'cover', borderRadius: 10, display: 'block' }}
          />
        </div>
      )}

      {/* 狀態提示 */}
      {status && (
        <div style={{
          background: statusColors[statusType],
          color: '#000',
          fontWeight: 600,
          fontSize: 12,
          padding: '5px 14px',
          borderRadius: 20,
          boxShadow: '0 4px 14px rgba(0,0,0,0.4)',
          animation: 'fade-in 0.2s ease',
          whiteSpace: 'nowrap',
        }}>
          {status}
        </div>
      )}

      {/* 拍照 FAB */}
      <label style={{
        width: 64, height: 64,
        borderRadius: '50%',
        background: uploading
          ? 'rgba(40,50,70,0.9)'
          : 'linear-gradient(135deg, rgba(0,212,255,0.9), rgba(0,255,136,0.8))',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        cursor: uploading ? 'not-allowed' : 'pointer',
        boxShadow: uploading
          ? 'none'
          : '0 0 0 1px rgba(0,212,255,0.4), 0 0 24px rgba(0,212,255,0.4), 0 8px 20px rgba(0,0,0,0.5)',
        transition: 'all 0.3s ease',
        userSelect: 'none',
        position: 'relative',
        overflow: 'hidden',
      }}>
        {/* 外輪光暈動畫 */}
        {!uploading && (
          <span style={{
            position: 'absolute', inset: -4,
            borderRadius: '50%',
            border: '2px solid rgba(0,212,255,0.3)',
            animation: 'pulse-ring 2s ease-out infinite',
          }} />
        )}
        {/* 轉圈動畫（上傳中） */}
        {uploading && (
          <span style={{
            position: 'absolute', inset: 4,
            borderRadius: '50%',
            border: '3px solid transparent',
            borderTop: '3px solid rgba(0,212,255,0.8)',
            animation: 'spin-glow 0.8s linear infinite',
          }} />
        )}
        <span style={{ fontSize: uploading ? 20 : 26, lineHeight: 1 }}>
          {uploading ? '' : '📷'}
        </span>
        <input
          ref={fileRef}
          type="file"
          accept="image/*"
          capture="environment"
          style={{ display: 'none' }}
          onChange={handleCapture}
          disabled={uploading}
        />
      </label>
    </div>
  );
}
