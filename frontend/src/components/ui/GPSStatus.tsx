import type React from 'react';
import type { GPSDevice } from '@/hooks/useGPSSync';
import { MinPanel } from './MinPanel';
import { PanelField, PanelFooter, PanelGrid, PanelSection, PanelStatus, type PanelStatusTone } from './PanelUi';

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
  statusBar?: boolean;
}

type StatusKey = 'connected' | 'connecting' | 'failed' | 'disconnected';

const STATUS_MAP: Record<StatusKey, { label: string; tone: PanelStatusTone }> = {
  connected: { label: '已連線', tone: 'live' },
  connecting: { label: '連線中', tone: 'warning' },
  failed: { label: '連線失敗', tone: 'danger' },
  disconnected: { label: '離線', tone: 'waiting' },
};

const S: Record<string, React.CSSProperties> = {
  row: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
  },
  label: {
    color: 'rgba(210, 230, 255, 0.58)',
    flexShrink: 0,
    fontSize: 11,
  },
  value: {
    color: '#fff',
    flex: 1,
    fontSize: 13,
    fontWeight: 700,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
  },
  button: {
    background: 'rgba(99, 199, 255, 0.12)',
    border: '1px solid rgba(99, 199, 255, 0.32)',
    borderRadius: 6,
    color: '#d7f2ff',
    cursor: 'pointer',
    flexShrink: 0,
    fontSize: 11,
    padding: '4px 9px',
  },
  dangerButton: {
    background: 'rgba(255,77,106,0.12)',
    border: '1px solid rgba(255,77,106,0.3)',
    color: 'var(--danger)',
    marginLeft: 'auto',
  },
  deviceList: {
    display: 'grid',
    gap: 4,
  },
  deviceItem: {
    border: '1px solid rgba(255,255,255,0.06)',
    borderRadius: 6,
    cursor: 'pointer',
    padding: '8px 10px',
  },
  deviceName: {
    color: '#fff',
    fontSize: 12,
    fontWeight: 700,
  },
  deviceMeta: {
    color: 'rgba(210, 230, 255, 0.62)',
    fontFamily: "'Cascadia Mono', Consolas, monospace",
    fontSize: 10,
    lineHeight: 1.5,
    marginTop: 3,
  },
  count: {
    background: 'rgba(255,255,255,0.1)',
    borderRadius: 10,
    color: '#fff',
    fontSize: 13,
    fontWeight: 700,
    padding: '1px 8px',
  },
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
  statusBar = false,
  style,
}: Props & { style?: React.CSSProperties }) {
  const key = (connectionStatus as StatusKey) in STATUS_MAP ? connectionStatus as StatusKey : 'disconnected';
  const st = STATUS_MAP[key];
  const isMobile = /iPhone|iPad|iPod|Android/i.test(navigator.userAgent);
  const summary = statusBar ? (
    <span className="status-summary status-summary--connection" aria-label="連線狀態摘要">
      <span className="status-summary__icon" aria-hidden="true">⌁</span>
      <span className={`status-summary__light status-summary__light--${st.tone}`} aria-hidden="true" />
      <span className="status-summary__count">{allDevices.size} 台</span>
    </span>
  ) : undefined;

  return (
    <MinPanel
      className={`panel-ui${statusBar ? ' status-panel status-panel--connection' : ''}`}
      title="連線狀態"
      style={style}
      defaultMinimized={statusBar}
      headerContent={summary}
      actions={!statusBar && <PanelStatus tone={st.tone} label={st.label} />}
    >
      <div style={S.row}>
        <span style={S.label}>裝置名稱</span>
        <span style={S.value}>{deviceName}</span>
        <span style={{ ...S.label, fontFamily: "'Cascadia Mono', Consolas, monospace" }}>{myDeviceId.slice(0, 8)}...</span>
        <button type="button" onClick={onRenameClick} style={S.button}>改名</button>
      </div>

      {isMobile && localGPS && localGPS.lat !== 0 && (
        <PanelGrid>
          <PanelField label="LAT" value={localGPS.lat.toFixed(6)} />
          <PanelField label="LON" value={localGPS.lon.toFixed(6)} />
          <PanelField label="ALT" value={`${localGPS.alt.toFixed(1)} m`} />
          <PanelField label="ACC" value={`${localGPS.accuracy.toFixed(0)} m`} />
        </PanelGrid>
      )}

      {!isMobile && allDevices.size > 0 && (
        <PanelSection>
          <div style={{ ...S.label, marginBottom: 8 }}>追蹤裝置 {allDevices.size}</div>
          <div style={S.deviceList}>
            {[...allDevices.entries()].map(([id, d]) => (
              <div
                key={id}
                onClick={() => onSelectDevice?.(id)}
                style={{
                  ...S.deviceItem,
                  background: selectedDeviceId === id ? 'rgba(255,255,255,0.15)' : 'rgba(255,255,255,0.04)',
                  borderColor: selectedDeviceId === id ? 'rgba(255,255,255,0.35)' : 'rgba(255,255,255,0.06)',
                }}
              >
                <div style={S.deviceName}>{d.deviceName}</div>
                <div style={S.deviceMeta}>
                  {d.lat.toFixed(5)}, {d.lon.toFixed(5)}
                  <span style={{ marginLeft: 6 }}>{d.alt.toFixed(0)} m</span>
                </div>
              </div>
            ))}
          </div>
        </PanelSection>
      )}

      <PanelFooter>
        <div style={S.row}>
          <span>軌跡點</span>
          <span style={S.count}>{uavPath.length}</span>
        </div>
        {uavPath.length > 0 && (
          <button type="button" onClick={onClearPath} style={{ ...S.button, ...S.dangerButton }}>
            清除軌跡
          </button>
        )}
      </PanelFooter>
    </MinPanel>
  );
}
