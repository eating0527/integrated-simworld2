import type React from 'react';
import type { GPSDevice } from '@/hooks/useGPSSync';
import { MinPanel } from './MinPanel';
import { PanelEmpty, PanelField, PanelFooter, PanelGrid, PanelStatus } from './PanelUi';

interface Props {
  deviceId?: string | null;
  device?: GPSDevice | null;
  isTracked: boolean;
  compact?: boolean;
  statusBar?: boolean;
  onTrack?: () => void;
}

function ageSeconds(device?: GPSDevice | null): number | null {
  if (!device?.lastUpdateTime) return null;
  return Math.max(0, Math.round((Date.now() - device.lastUpdateTime) / 1000));
}

const S: Record<string, React.CSSProperties> = {
  name: {
    fontSize: 15,
    fontWeight: 700,
    marginBottom: 8,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
  },
  id: {
    fontSize: 10,
    color: 'rgba(210, 230, 255, 0.55)',
    fontFamily: "'Cascadia Mono', Consolas, monospace",
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
  },
  button: {
    border: '1px solid rgba(99, 199, 255, 0.38)',
    background: 'rgba(99, 199, 255, 0.12)',
    color: '#d7f2ff',
    borderRadius: 6,
    padding: '5px 9px',
    fontSize: 11,
    cursor: 'pointer',
    flexShrink: 0,
  },
};

export function AircraftTelemetry({ deviceId, device, isTracked, compact = false, statusBar = false, onTrack }: Props) {
  const age = ageSeconds(device);
  const summary = statusBar ? (
    <span className="status-summary status-summary--telemetry" aria-label="GPS 狀態摘要">
      <span className="status-summary__icon" aria-hidden="true">⌖</span>
      {device ? (
        <span className="status-summary__data">
          <span>{device.lat.toFixed(3)}</span>
          <span>{device.lon.toFixed(3)}</span>
          <span>{device.alt.toFixed(1)}</span>
        </span>
      ) : <span className="status-summary__na">N/A</span>}
    </span>
  ) : undefined;

  return (
    <MinPanel
      title={statusBar ? 'GPS 狀態' : '無人機遙測'}
      className={`panel-ui${statusBar ? ' status-panel status-panel--telemetry' : ''}`}
      defaultMinimized={statusBar}
      headerContent={summary}
      style={compact ? {
        position: 'fixed',
        right: 12,
        bottom: 12,
        left: 12,
        zIndex: 998,
        width: 'calc(100vw - 24px)',
        maxWidth: 320,
      } : undefined}
      actions={!statusBar && (
        <PanelStatus tone={device ? 'live' : 'waiting'} label={device ? 'Live' : 'Waiting'} />
      )}
    >
      {!device ? (
        <PanelEmpty>
          Waiting for AP3 MAVLink GPS. Keep the controller connected by USB and the AP3 bridge running.
        </PanelEmpty>
      ) : (
        <>
          <div style={S.name}>{device.deviceName || 'M4P TOP Aircraft'}</div>
          <PanelGrid>
            <PanelField label="Latitude" value={device.lat.toFixed(7)} />
            <PanelField label="Longitude" value={device.lon.toFixed(7)} />
            <PanelField label="Altitude" value={`${device.alt.toFixed(2)} m`} />
            <PanelField label="Accuracy" value={`${device.accuracy.toFixed(1)} m`} />
          </PanelGrid>
          <PanelFooter>
            <span style={S.id}>
              {deviceId} {age !== null ? `- ${age}s ago` : ''}
            </span>
            {!isTracked && onTrack && (
              <button type="button" style={S.button} onClick={onTrack}>
                Track
              </button>
            )}
          </PanelFooter>
        </>
      )}
    </MinPanel>
  );
}
