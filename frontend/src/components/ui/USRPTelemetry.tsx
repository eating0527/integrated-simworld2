import type React from 'react';
import type { USRPSpectrumEvent } from '@/hooks/useGPSSync';

interface Props {
  event?: USRPSpectrumEvent | null;
}

function ageSeconds(event?: USRPSpectrumEvent | null): number | null {
  if (!event?.timestamp) return null;
  return Math.max(0, Math.round(Date.now() / 1000 - event.timestamp));
}

const S: Record<string, React.CSSProperties> = {
  panel: {
    position: 'fixed',
    top: 132,
    left: 276,
    zIndex: 997,
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
    marginTop: 10,
    paddingTop: 9,
    borderTop: '1px solid rgba(120, 180, 255, 0.12)',
    fontSize: 10,
    color: 'rgba(210, 230, 255, 0.55)',
    fontFamily: "'Cascadia Mono', Consolas, monospace",
  },
  empty: {
    fontSize: 12,
    color: 'rgba(220, 235, 255, 0.68)',
    lineHeight: 1.5,
  },
};

export function USRPTelemetry({ event }: Props) {
  const age = ageSeconds(event);

  return (
    <div style={S.panel}>
      <div style={S.header}>
        <div style={S.title}>USRP Spectrum</div>
        <div style={S.pill}>
          <span style={{ ...S.dot, background: event ? '#00e58a' : '#56657a' }} />
          {event ? 'Live' : 'Waiting'}
        </div>
      </div>

      {!event ? (
        <div style={S.empty}>
          Waiting for `usrp-spectrum` events from the B210 bridge.
        </div>
      ) : (
        <>
          <div style={S.name}>{event.deviceName || 'USRP B210 Sensor'}</div>
          <div style={S.grid}>
            <div style={S.field}>
              <span style={S.label}>Center Freq</span>
              <span style={S.value}>{(event.center_freq_hz / 1e6).toFixed(3)} MHz</span>
            </div>
            <div style={S.field}>
              <span style={S.label}>Sample Rate</span>
              <span style={S.value}>{(event.sample_rate_hz / 1e6).toFixed(3)} Msps</span>
            </div>
            <div style={S.field}>
              <span style={S.label}>Mean Power</span>
              <span style={S.value}>{event.mean_power_dbfs.toFixed(2)} dBFS</span>
            </div>
            <div style={S.field}>
              <span style={S.label}>Peak Power</span>
              <span style={S.value}>{event.peak_power_dbfs.toFixed(2)} dBFS</span>
            </div>
            <div style={S.field}>
              <span style={S.label}>Gain</span>
              <span style={S.value}>{event.gain_db.toFixed(1)} dB</span>
            </div>
            <div style={S.field}>
              <span style={S.label}>Samples</span>
              <span style={S.value}>{event.sample_count}</span>
            </div>
          </div>
          <div style={S.footer}>
            {event.deviceId}
            {age !== null ? ` - ${age}s ago` : ''}
          </div>
        </>
      )}
    </div>
  );
}
