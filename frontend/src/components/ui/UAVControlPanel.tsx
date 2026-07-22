import type React from 'react';
import { useRef, useCallback } from 'react';
import { ManualDirection } from '../../hooks/useManualControl';
import { MinPanel } from './MinPanel';

const LONG_PRESS_DELAY = 150;   // ms before repeat kicks in
const LONG_PRESS_INTERVAL = 80; // ms between repeated steps

interface UAVControlPanelProps {
  auto: boolean;
  uavAnimation: boolean;
  uavPosition: [number, number, number];
  onToggleAuto: () => void;
  onToggleAnimation: () => void;
  onManualControl: (direction: ManualDirection) => void;
}

// Static styles
const S: Record<string, React.CSSProperties> = {
  panel: {
    background: 'rgba(8, 16, 32, 0.82)',
    backdropFilter: 'blur(12px)',
    border: '1px solid rgba(80, 160, 255, 0.25)',
    borderRadius: '12px',
    padding: '16px',
    color: '#c8dff8',
    fontFamily: "'Segoe UI', system-ui, sans-serif",
    fontSize: '13px',
    userSelect: 'none',
    minWidth: '220px',
    boxShadow: '0 4px 32px rgba(0, 60, 180, 0.3)',
  },
  title: {
    fontSize: '11px',
    fontWeight: 700,
    letterSpacing: '0.12em',
    textTransform: 'uppercase',
    color: '#6aafff',
    marginBottom: '12px',
    borderBottom: '1px solid rgba(80, 160, 255, 0.2)',
    paddingBottom: '8px',
  },
  row: {
    display: 'flex',
    gap: '8px',
    marginBottom: '8px',
  },
  sectionLabel: {
    fontSize: '11px',
    color: '#4a7aaa',
    marginBottom: '6px',
    letterSpacing: '0.08em',
    textTransform: 'uppercase',
  },
  dpad: {
    display: 'grid',
    gridTemplateColumns: 'repeat(3, 36px)',
    gridTemplateRows: 'repeat(3, 36px)',
    gap: '3px',
    margin: '0 auto 8px',
    width: 'fit-content',
  },
  dpadEmpty: {
    width: '36px',
    height: '36px',
  },
  altRow: {
    display: 'flex',
    gap: '6px',
    marginBottom: '8px',
    justifyContent: 'center',
  },
  coords: {
    marginTop: '10px',
    borderTop: '1px solid rgba(80,160,255,0.15)',
    paddingTop: '8px',
    display: 'flex',
    justifyContent: 'space-between',
    gap: '4px',
  },
  coordItem: {
    textAlign: 'center',
    flex: 1,
  },
  coordLabel: {
    fontSize: '10px',
    color: '#4a7aaa',
    letterSpacing: '0.08em',
  },
  coordValue: {
    fontSize: '12px',
    color: '#9ac8f5',
    fontVariantNumeric: 'tabular-nums',
  },
};

// Dynamic style factories (defined outside Record to keep proper function types)
function toggleBtn(active: boolean, accent: string): React.CSSProperties {
  return {
    flex: 1,
    padding: '6px 0',
    borderRadius: '7px',
    border: `1px solid ${active ? accent : 'rgba(80,160,255,0.2)'}`,
    background: active ? `${accent}33` : 'rgba(255,255,255,0.04)',
    color: active ? accent : '#7aa8d8',
    fontWeight: 600,
    fontSize: '12px',
    cursor: 'pointer',
    transition: 'background-color 0.18s, border-color 0.18s, color 0.18s',
    letterSpacing: '0.04em',
  };
}

function dpadBtn(active = false): React.CSSProperties {
  return {
    width: '36px',
    height: '36px',
    borderRadius: '6px',
    border: '1px solid rgba(80,160,255,0.25)',
    background: active ? 'rgba(80,160,255,0.35)' : 'rgba(255,255,255,0.05)',
    color: '#9ac8f5',
    fontSize: '15px',
    cursor: 'pointer',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    transition: 'background 0.12s',
    padding: 0,
  };
}

function altBtn(): React.CSSProperties {
  return {
    flex: 1,
    padding: '5px 0',
    borderRadius: '6px',
    border: '1px solid rgba(80,160,255,0.2)',
    background: 'rgba(255,255,255,0.04)',
    color: '#9ac8f5',
    fontSize: '11px',
    cursor: 'pointer',
    transition: 'background 0.12s',
    textAlign: 'center',
  };
}

/** Hook that fires a callback once immediately, then repeatedly while held down */
function useLongPress(callback: () => void) {
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const start = useCallback(() => {
    callback();
    timerRef.current = setTimeout(() => {
      intervalRef.current = setInterval(callback, LONG_PRESS_INTERVAL);
    }, LONG_PRESS_DELAY);
  }, [callback]);

  const stop = useCallback(() => {
    if (timerRef.current) { clearTimeout(timerRef.current); timerRef.current = null; }
    if (intervalRef.current) { clearInterval(intervalRef.current); intervalRef.current = null; }
  }, []);

  return { start, stop };
}

function DpadButton({
  direction,
  label,
  style,
  onManualControl,
}: {
  direction: ManualDirection;
  label: string;
  style?: React.CSSProperties;
  onManualControl: (d: ManualDirection) => void;
}) {
  const cb = useCallback(() => onManualControl(direction), [direction, onManualControl]);
  const { start, stop } = useLongPress(cb);
  return (
    <button
      style={{ ...dpadBtn(), ...style }}
      onMouseDown={start}
      onMouseUp={stop}
      onMouseLeave={stop}
      onTouchStart={(e) => { e.preventDefault(); start(); }}
      onTouchEnd={stop}
      onTouchCancel={stop}
      title={direction ?? ''}
    >
      {label}
    </button>
  );
}

function AltButton({
  direction,
  label,
  onManualControl,
}: {
  direction: ManualDirection;
  label: string;
  onManualControl: (d: ManualDirection) => void;
}) {
  const cb = useCallback(() => onManualControl(direction), [direction, onManualControl]);
  const { start, stop } = useLongPress(cb);
  return (
    <button
      style={altBtn()}
      onMouseDown={start}
      onMouseUp={stop}
      onMouseLeave={stop}
      onTouchStart={(e) => { e.preventDefault(); start(); }}
      onTouchEnd={stop}
      onTouchCancel={stop}
    >
      {label}
    </button>
  );
}

export function UAVControlPanel({
  auto,
  uavAnimation,
  uavPosition,
  onToggleAuto,
  onToggleAnimation,
  onManualControl,
}: UAVControlPanelProps) {
  const [x, y, z] = uavPosition;

  return (
    <MinPanel title="無人機控制" className="panel-ui uav-control-panel" defaultMinimized>
          <div style={{ ...S.panel, borderRadius: 0, border: 'none', boxShadow: 'none' }}>

      {/* Mode toggles */}
      <div style={S.row}>
        <button style={toggleBtn(auto, '#4af')} onClick={onToggleAuto}>
          ⟳ AUTO
        </button>
        <button style={toggleBtn(!auto, '#f8a')} onClick={onToggleAuto}>
          ✦ MANUAL
        </button>
      </div>
      <div style={{ ...S.row, marginBottom: '12px' }}>
        <button style={toggleBtn(uavAnimation, '#8f8')} onClick={onToggleAnimation}>
          {uavAnimation ? '▶ ANIM ON' : '⏸ ANIM OFF'}
        </button>
      </div>

      {/* D-pad — only usable in manual mode */}
      {!auto && (
        <>
          <div style={S.sectionLabel}>Direction</div>

          <div style={S.dpad}>
            {/* Row 1: ↖ ↑ ↗ */}
            <DpadButton direction="left-up"    label="↖" onManualControl={onManualControl} />
            <DpadButton direction="up"         label="↑" onManualControl={onManualControl} />
            <DpadButton direction="right-up"   label="↗" onManualControl={onManualControl} />
            {/* Row 2: ← · → */}
            <DpadButton direction="left"       label="←" onManualControl={onManualControl} />
            <div style={S.dpadEmpty} />
            <DpadButton direction="right"      label="→" onManualControl={onManualControl} />
            {/* Row 3: ↙ ↓ ↘ */}
            <DpadButton direction="left-down"  label="↙" onManualControl={onManualControl} />
            <DpadButton direction="down"       label="↓" onManualControl={onManualControl} />
            <DpadButton direction="right-down" label="↘" onManualControl={onManualControl} />
          </div>

          {/* Ascend / Descend */}
          <div style={S.altRow}>
            <AltButton direction="ascend"       label="▲ Ascend"  onManualControl={onManualControl} />
            <AltButton direction="descend"      label="▼ Descend" onManualControl={onManualControl} />
          </div>

          {/* Rotate */}
          <div style={S.altRow}>
            <AltButton direction="rotate-left"  label="↺ Rot L"  onManualControl={onManualControl} />
            <AltButton direction="rotate-right" label="↻ Rot R"  onManualControl={onManualControl} />
          </div>
        </>
      )}

      {/* Coordinates */}
      <div style={S.coords}>
        <div style={S.coordItem}>
          <div style={S.coordLabel}>X</div>
          <div style={S.coordValue}>{x.toFixed(1)}</div>
        </div>
        <div style={S.coordItem}>
          <div style={S.coordLabel}>Y</div>
          <div style={S.coordValue}>{y.toFixed(1)}</div>
        </div>
        <div style={S.coordItem}>
          <div style={S.coordLabel}>Z</div>
          <div style={S.coordValue}>{z.toFixed(1)}</div>
        </div>
      </div>
          </div>
    </MinPanel>
  );
}
