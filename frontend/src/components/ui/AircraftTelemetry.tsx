import type React from 'react';
import type { GPSDevice } from '@/hooks/useGPSSync';

interface Props {
  deviceId?: string | null;
  device?: GPSDevice | null;
  isTracked: boolean;
  onTrack?: () => void;
}

function ageSeconds(device?: GPSDevice | null): number | null {
  if (!device?.lastUpdateTime) return null;
  return Math.max(0, Math.round((Date.now() - device.lastUpdateTime) / 1000));
}

const S: Record<string, React.CSSProperties> = {
  panel: {
    position: 'fixed',
    top: 14,
    left: 276,
    zIndex: 998,
    width: 300,
    background: 'rgba(8, 12, 24, 0.82)',
    border: '1px solid rgba(80, 180, 255, 0.24)',
    borderRadius: 8,
    padding: '12px 14px',
    color: '#e8f2ff',
    boxShadow: '0 10px 30px rgba(0, 0, 0, 0.45)',
    backdropFilter: 'blur(14px)',
    WebkitBackdropFilter: 'blur(14px)',
    fontFamily: "'Segoe UI', system-ui, sans-serif",
    pointerEvents: 'auto',
  },
  header: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: 10,
    marginBottom: 10,
  },
  title: {
    fontSize: 11,
    fontWeight: 700,
    letterSpacing: '0.1em',
    textTransform: 'uppercase',
    color: '#63c7ff',
  },
  pill: {
    display: 'inline-flex',
    alignItems: 'center',
    gap: 6,
    fontSize: 11,
    color: '#b8d8ff',
  },
  dot: {
    width: 8,
    height: 8,
    borderRadius: '50%',
    background: '#00e58a',
    boxShadow: '0 0 10px rgba(0, 229, 138, 0.85)',
  },
  name: {
    fontSize: 15,
    fontWeight: 700,
    marginBottom: 8,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
  },
  grid: {
    display: 'grid',
    gridTemplateColumns: '1fr 1fr',
    gap: 8,
  },
  field: {
    background: 'rgba(255, 255, 255, 0.055)',
    border: '1px solid rgba(255, 255, 255, 0.08)',
    borderRadius: 6,
    padding: '7px 8px',
  },
  label: {
    display: 'block',
    fontSize: 10,
    color: 'rgba(210, 230, 255, 0.58)',
    letterSpacing: '0.08em',
    textTransform: 'uppercase',
    marginBottom: 3,
  },
  value: {
    display: 'block',
    fontSize: 13,
    fontFamily: "'Cascadia Mono', Consolas, monospace",
    color: '#ffffff',
  },
  footer: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: 8,
    marginTop: 10,
    paddingTop: 9,
    borderTop: '1px solid rgba(120, 180, 255, 0.12)',
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
  empty: {
    fontSize: 12,
    color: 'rgba(220, 235, 255, 0.68)',
    lineHeight: 1.5,
  },
};

export function AircraftTelemetry({ deviceId, device, isTracked, onTrack }: Props) {
  const age = ageSeconds(device);

  return (
    <div style={S.panel}>
      <div style={S.header}>
        <div style={S.title}>Aircraft Telemetry</div>
        <div style={S.pill}>
          <span style={{ ...S.dot, background: device ? '#00e58a' : '#56657a' }} />
          {device ? 'Live' : 'Waiting'}
        </div>
      </div>

      {!device ? (
        <div style={S.empty}>
          Waiting for AP3 MAVLink GPS. Keep the controller connected by USB and the AP3 bridge running.
        </div>
      ) : (
        <>
          <div style={S.name}>{device.deviceName || 'M4P TOP Aircraft'}</div>
          <div style={S.grid}>
            <div style={S.field}>
              <span style={S.label}>Latitude</span>
              <span style={S.value}>{device.lat.toFixed(7)}</span>
            </div>
            <div style={S.field}>
              <span style={S.label}>Longitude</span>
              <span style={S.value}>{device.lon.toFixed(7)}</span>
            </div>
            <div style={S.field}>
              <span style={S.label}>Altitude</span>
              <span style={S.value}>{device.alt.toFixed(2)} m</span>
            </div>
            <div style={S.field}>
              <span style={S.label}>Accuracy</span>
              <span style={S.value}>{device.accuracy.toFixed(1)} m</span>
            </div>
          </div>
          <div style={S.footer}>
            <span style={S.id}>
              {deviceId} {age !== null ? `- ${age}s ago` : ''}
            </span>
            {!isTracked && onTrack && (
              <button type="button" style={S.button} onClick={onTrack}>
                Track
              </button>
            )}
          </div>
        </>
      )}
    </div>
  );
}
