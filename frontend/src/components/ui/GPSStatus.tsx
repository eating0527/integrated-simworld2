/**
 * GPSStatus — 左上角連線狀態 + GPS HUD（Glassmorphism）
 */
import { GPSDevice } from '@/hooks/useGPSSync';

interface Props {
  myDeviceId: string;
  deviceName: string;
  onRenameClick: () => void;
  allDevices: Map<string, GPSDevice>;
  uavPath: Array<{ x: number; y: number; z: number }>;
  onClearPath: () => void;
  connectionStatus: string;
  localGPS?: { lat: number; lon: number; alt: number; accuracy: number } | null;
  selectedDeviceId?: string | null;
  onSelectDevice?: (id: string) => void;
}

type StatusKey = 'connected' | 'connecting' | 'failed' | 'disconnected';

const STATUS_MAP: Record<StatusKey, { dot: string; label: string; pulse: boolean }> = {
  connected:    { dot: '#00ff88', label: '已連線',  pulse: true  },
  connecting:   { dot: '#ffb020', label: '連線中…', pulse: true  },
  failed:       { dot: '#ff4d6a', label: '連線失敗', pulse: false },
  disconnected: { dot: '#3e4f72', label: '離線',    pulse: false },
};

export function GPSStatus({
  myDeviceId,
  deviceName,
  onRenameClick,
  allDevices,
  uavPath,
  onClearPath,
  connectionStatus,
  localGPS,
  selectedDeviceId,
  onSelectDevice,
  style,
}: Props & { style?: React.CSSProperties }) {
  const key = (connectionStatus as StatusKey) in STATUS_MAP ? connectionStatus as StatusKey : 'disconnected';
  const st = STATUS_MAP[key];
  const isMobile = /iPhone|iPad|iPod|Android/i.test(navigator.userAgent);

  return (
    <div style={{
      position: 'fixed', top: 14, right: 14, zIndex: 999,
      background: 'rgba(8,12,28,0.75)',
      backdropFilter: 'blur(18px)',
      WebkitBackdropFilter: 'blur(18px)',
      borderRadius: 'var(--panel-radius)',
      padding: '14px 16px',
      color: 'white',
      fontSize: 13,
      minWidth: 240,
      border: '1px solid rgba(120,180,255,0.14)',
      boxShadow: '0 8px 32px rgba(0,0,0,0.55), inset 0 1px 0 rgba(255,255,255,0.06)',
      animation: 'slide-in-left 0.3s ease',
      ...style
    }}>

      {/* ── 連線狀態 ── */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12 }}>
        <span style={{
          color: 'white',
          fontSize: 12,
          fontWeight: 700,
          letterSpacing: '0.08em',
          textTransform: 'uppercase',
          whiteSpace: 'nowrap',
        }}>連線狀態</span>
        <div style={{ position: 'relative', width: 10, height: 10, flexShrink: 0 }}>
          {st.pulse && (
            <span style={{
              position: 'absolute', inset: 0,
              borderRadius: '50%',
              background: st.dot,
              opacity: 0.4,
              animation: 'pulse-ring 1.4s ease-out infinite',
            }} />
          )}
          <span style={{
            position: 'absolute', inset: 0,
            borderRadius: '50%',
            background: st.dot,
            boxShadow: `0 0 8px ${st.dot}`,
            animation: st.pulse ? 'pulse-dot 1.4s ease-in-out infinite' : 'none',
          }} />
        </div>
        <span style={{ color: 'white', fontWeight: 600, fontSize: 13, letterSpacing: '0.02em' }}>
          {st.label}
        </span>
        <span style={{ color: 'white', fontSize: 11, marginLeft: 'auto', fontFamily: 'monospace' }}>
          {myDeviceId.slice(0, 8)}…
        </span>
      </div>

      {/* 分隔線 */}
      <div style={{ height: 1, background: 'rgba(120,180,255,0.08)', marginBottom: 12 }} />

      {/* ── 裝置名稱 ── */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
        <span style={{ color: 'white', fontSize: 11, flexShrink: 0 }}>裝置名稱</span>
        <span style={{
          color: 'white', fontWeight: 600, fontSize: 13,
          flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
        }}>{deviceName}</span>
        <button
          onClick={onRenameClick}
          style={{
            background: 'rgba(255,255,255,0.1)',
            border: '1px solid rgba(255,255,255,0.3)',
            color: 'white',
            fontSize: 11, padding: '3px 10px',
            borderRadius: 20, cursor: 'pointer',
            transition: 'background 0.2s',
            flexShrink: 0,
          }}
          onMouseEnter={e => (e.currentTarget.style.background = 'rgba(255,255,255,0.2)')}
          onMouseLeave={e => (e.currentTarget.style.background = 'rgba(255,255,255,0.1)')}
        >改名</button>
      </div>

      {/* ── 本機 GPS（手機端） ── */}
      {isMobile && localGPS && localGPS.lat !== 0 && (
        <div style={{
          background: 'rgba(255,255,255,0.07)',
          border: '1px solid rgba(255,255,255,0.15)',
          borderRadius: 10, padding: '8px 12px', marginBottom: 10,
        }}>
          <div style={{ color: 'white', fontSize: 12, fontFamily: 'monospace', lineHeight: 1.7 }}>
            <span style={{ color: 'white', fontSize: 10 }}>LAT </span>{localGPS.lat.toFixed(6)}
            <br />
            <span style={{ color: 'white', fontSize: 10 }}>LON </span>{localGPS.lon.toFixed(6)}
            <br />
            <span style={{ color: 'white', fontSize: 10 }}>ALT </span>{localGPS.alt.toFixed(1)} m
            <span style={{ color: 'white', fontSize: 10, marginLeft: 8 }}>±{localGPS.accuracy.toFixed(0)} m</span>
          </div>
        </div>
      )}

      {/* ── 線上裝置列表（桌面端） ── */}
      {!isMobile && allDevices.size > 0 && (
        <div style={{ marginBottom: 10 }}>
          <div style={{
            color: 'white', fontSize: 10,
            letterSpacing: '0.08em', textTransform: 'uppercase',
            marginBottom: 8,
          }}>線上裝置 · {allDevices.size}</div>
          {[...allDevices.entries()].map(([id, d]) => (
            <div
              key={id}
              onClick={() => onSelectDevice?.(id)}
              style={{
                cursor: 'pointer',
                padding: '8px 10px',
                borderRadius: 10,
                marginBottom: 4,
                background: selectedDeviceId === id
                  ? 'rgba(255,255,255,0.15)'
                  : 'rgba(255,255,255,0.04)',
                border: `1px solid ${selectedDeviceId === id ? 'rgba(255,255,255,0.35)' : 'rgba(255,255,255,0.06)'}`,
                transition: 'background 0.2s, border 0.2s',
              }}
              onMouseEnter={e => {
                if (selectedDeviceId !== id)
                  e.currentTarget.style.background = 'rgba(255,255,255,0.07)';
              }}
              onMouseLeave={e => {
                if (selectedDeviceId !== id)
                  e.currentTarget.style.background = 'rgba(255,255,255,0.04)';
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <span style={{ fontSize: 10 }}>📱</span>
                <span style={{ color: 'white', fontWeight: 600, fontSize: 12 }}>
                  {d.deviceName}
                </span>
              </div>
              <div style={{
                color: 'white', fontSize: 10,
                fontFamily: 'monospace', marginTop: 3, lineHeight: 1.5,
              }}>
                {d.lat.toFixed(5)}, {d.lon.toFixed(5)}
                <span style={{ marginLeft: 6 }}>↕ {d.alt.toFixed(0)} m</span>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* 分隔線 */}
      <div style={{ height: 1, background: 'rgba(120,180,255,0.08)', marginBottom: 10 }} />

      {/* ── 軌跡資訊 ── */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <span style={{ color: 'white', fontSize: 11 }}>軌跡點</span>
        <span style={{
          color: 'white', fontWeight: 700, fontSize: 13,
          background: 'rgba(255,255,255,0.1)',
          padding: '1px 8px', borderRadius: 10,
        }}>{uavPath.length}</span>
        {uavPath.length > 0 && (
          <button
            onClick={onClearPath}
            style={{
              marginLeft: 'auto',
              background: 'rgba(255,77,106,0.12)',
              border: '1px solid rgba(255,77,106,0.3)',
              color: 'var(--accent-red)',
              fontSize: 11, padding: '3px 12px',
              borderRadius: 20, cursor: 'pointer',
              transition: 'background 0.2s',
            }}
            onMouseEnter={e => (e.currentTarget.style.background = 'rgba(255,77,106,0.22)')}
            onMouseLeave={e => (e.currentTarget.style.background = 'rgba(255,77,106,0.12)')}
          >清除軌跡</button>
        )}
      </div>
    </div>
  );
}
