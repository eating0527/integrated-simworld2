import React from 'react';
import { useDeviceStore } from '../../store/useDeviceStore';
import type { Device, DeviceRole } from '../../types/device';
import type { SceneFrame } from '../../types/sceneFrame';
import { enuToGps, enuToGrid, enuToThree, gpsToEnu, threeToEnu } from '../../utils/geo';
import { MinPanel } from './MinPanel';

type CoordMode = 'gps' | 'xyz';
type Position = [number, number, number];
type PositionDraft = Record<'lat' | 'lon' | 'alt' | 'x' | 'y' | 'z', string>;

type CoordAxis = keyof PositionDraft;

function formatPosition(device: Device, mode: CoordMode, frame: SceneFrame): PositionDraft {
  if (mode === 'xyz') {
    return { lat: '', lon: '', alt: '', x: String(device.x), y: String(device.y), z: String(device.z) };
  }

  const gps = enuToGps(threeToEnu([device.x, device.y, device.z]), frame, frame.alt_mode);
  return { lat: String(gps.lat), lon: String(gps.lon), alt: String(gps.alt), x: '', y: '', z: '' };
}

function isCompleteNumber(value: string): boolean {
  return /^-?(?:\d+(?:\.\d*)?|\.\d+)$/.test(value.trim());
}

function parseNumber(value: string): number | null {
  if (!isCompleteNumber(value)) return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function draftToThree(draft: PositionDraft, mode: CoordMode, frame: SceneFrame): Position | null {
  if (mode === 'xyz') {
    const values = [draft.x, draft.y, draft.z].map(parseNumber);
    return values.every((value): value is number => value !== null)
      ? [values[0], values[1], values[2]]
      : null;
  }

  const lat = parseNumber(draft.lat);
  const lon = parseNumber(draft.lon);
  const alt = parseNumber(draft.alt);
  if (lat === null || lon === null || alt === null || lat < -90 || lat > 90 || lon < -180 || lon > 180) {
    return null;
  }
  return enuToThree(gpsToEnu({ lat, lon, alt }, frame, frame.alt_mode));
}

function isInsideScene(position: Position, frame: SceneFrame): boolean {
  return enuToGrid(threeToEnu(position), frame).inside_extent;
}

function GlobeIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" aria-hidden="true">
      <circle cx="12" cy="12" r="9" />
      <path d="M3 12h18M12 3c2.2 2.4 3.3 5.4 3.3 9s-1.1 6.6-3.3 9c-2.2-2.4-3.3-5.4-3.3-9S9.8 5.4 12 3Z" />
    </svg>
  );
}

function AxesIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" aria-hidden="true">
      <path d="M5 19V5M5 19h14M5 19l5-5M5 5l4 4M19 19l-4-4M19 5l-4 4" />
    </svg>
  );
}

function CoordinateInput({
  label,
  value,
  inputId,
  error,
  errorId,
  onChange,
}: {
  label: string;
  value: string;
  inputId: string;
  error: boolean;
  errorId: string;
  onChange: (value: string) => void;
}) {
  return (
    <input
      id={inputId}
      type="text"
      inputMode="decimal"
      className="dp-input dp-input-sm"
      value={value}
      aria-label={label}
      aria-invalid={error}
      aria-describedby={error ? errorId : undefined}
      onChange={(event) => onChange(event.target.value)}
    />
  );
}

interface DeviceRowProps {
  device: Device;
  onUpdate: (patch: Partial<Omit<Device, 'id' | 'role'>>) => void;
  onRemove?: () => void;
  showPower: boolean;
  coordMode: CoordMode;
  sceneFrame: SceneFrame;
  onApplyPosition: (position: Position) => void;
  coordinateInputsId: string;
  onSaveDefault: () => void;
  onApplyDefault: () => void;
  onZero: () => void;
}

function DeviceRow({
  device,
  onUpdate,
  onRemove,
  showPower,
  coordMode,
  sceneFrame,
  onApplyPosition,
  coordinateInputsId,
  onSaveDefault,
  onApplyDefault,
  onZero,
}: DeviceRowProps) {
  const [draft, setDraft] = React.useState(() => formatPosition(device, coordMode, sceneFrame));

  React.useEffect(() => {
    setDraft(formatPosition(device, coordMode, sceneFrame));
  }, [device.x, device.y, device.z, coordMode, sceneFrame]);

  const candidate = draftToThree(draft, coordMode, sceneFrame);
  const error = candidate === null
    ? '請輸入有效座標'
    : isInsideScene(candidate, sceneFrame) ? null : '超出目前場景範圍';
  const fields: Array<[CoordAxis, string]> = coordMode === 'gps'
    ? [['lat', `緯度 ${device.name}`], ['lon', `經度 ${device.name}`], ['alt', `高度 ${device.name}`]]
    : [['x', `X ${device.name}`], ['y', `Y ${device.name}`], ['z', `Z ${device.name}`]];
  const errorId = `${coordinateInputsId}-error`;
  const nameInputId = `${coordinateInputsId}-name`;
  const powerInputId = `${coordinateInputsId}-power`;

  return (
    <div className="dp-device-row">
      <div className="dp-field-row">
        <label className="dp-label" htmlFor={nameInputId}>名稱</label>
        <input
          id={nameInputId}
          className="dp-input"
          value={device.name}
          onChange={(event) => onUpdate({ name: event.target.value })}
        />
        {onRemove && (
          <button className="dp-btn-remove" onClick={onRemove} title="刪除" aria-label="刪除裝置">
            ✕
          </button>
        )}
      </div>

      <div className="dp-coordinate-fields" id={coordinateInputsId}>
        {fields.map(([axis, label]) => (
          <label key={axis} className="dp-coordinate-field">
            <span>{label.split(' ')[0]}</span>
            <CoordinateInput
              label={label}
              value={draft[axis]}
              inputId={`${coordinateInputsId}-${axis}`}
              error={error !== null}
              errorId={errorId}
              onChange={(value) => setDraft((current) => ({ ...current, [axis]: value }))}
            />
          </label>
        ))}
        {error && <span id={errorId} className="dp-coordinate-error">{error}</span>}
      </div>

      {showPower && (
        <div className="dp-field-row">
          <label className="dp-label" htmlFor={powerInputId}>功率</label>
          <input
            id={powerInputId}
            type="number"
            className="dp-input dp-input-sm"
            value={device.powerDbm ?? 0}
            onChange={(event) => onUpdate({ powerDbm: parseFloat(event.target.value) || 0 })}
          />
          <span className="dp-unit">dBm</span>
        </div>
      )}

      <div className="dp-field-row">
        <button
          className="dp-btn-apply"
          disabled={error !== null}
          onClick={() => {
            if (candidate !== null && error === null) onApplyPosition(candidate);
          }}
        >
          套用位置
        </button>
      </div>

      <div className="dp-field-row dp-action-row">
        <button className="dp-btn-overwrite" onClick={onSaveDefault}>覆寫預設</button>
        <button className="dp-btn-apply-default" onClick={onApplyDefault}>套用預設</button>
        <button className="dp-btn-zero" onClick={onZero}>歸零</button>
      </div>
    </div>
  );
}

interface SectionProps {
  title: string;
  role: DeviceRole;
  devices: Device[];
  coordMode: CoordMode;
  sceneFrame: SceneFrame;
  coordinateInputsId: string;
  canAdd?: boolean;
  showPower?: boolean;
  onApplyRxPosition?: (position: Position) => void;
}

function Section({
  title,
  role,
  devices,
  coordMode,
  sceneFrame,
  coordinateInputsId,
  canAdd = false,
  showPower = false,
  onApplyRxPosition,
}: SectionProps) {
  const {
    addDevice,
    removeDevice,
    updateDevice,
    saveDeviceDefault,
    applyDeviceDefault,
    zeroDevice,
    deviceDefaults,
  } = useDeviceStore();

  const handleApplyPosition = (device: Device, position: Position) => {
    updateDevice(device.id, { x: position[0], y: position[1], z: position[2] });
    if (device.role === 'rx') onApplyRxPosition?.(position);
  };

  const handleApplyDefault = (device: Device) => {
    const savedDefault = deviceDefaults[device.id];
    applyDeviceDefault(device.id);
    if (device.role === 'rx' && savedDefault && onApplyRxPosition) {
      onApplyRxPosition([savedDefault.x, savedDefault.y, savedDefault.z]);
    }
  };

  const handleZero = (device: Device) => {
    zeroDevice(device.id);
    if (device.role === 'rx' && onApplyRxPosition) onApplyRxPosition([0, 0, 0]);
  };

  return (
    <div className="dp-section">
      <div className="dp-section-header">
        <span className="dp-section-title">{title}</span>
        {canAdd && <button className="dp-btn-add" onClick={() => addDevice(role)}>+ 新增</button>}
      </div>
      {devices.map((device) => (
        <DeviceRow
          key={device.id}
          device={device}
          coordMode={coordMode}
          sceneFrame={sceneFrame}
          coordinateInputsId={`${coordinateInputsId}-${device.id}`}
          showPower={showPower}
          onUpdate={(patch) => updateDevice(device.id, patch)}
          onRemove={canAdd ? () => removeDevice(device.id) : undefined}
          onApplyPosition={(position) => handleApplyPosition(device, position)}
          onSaveDefault={() => saveDeviceDefault(device.id)}
          onApplyDefault={() => handleApplyDefault(device)}
          onZero={() => handleZero(device)}
        />
      ))}
    </div>
  );
}

interface DevicePanelProps {
  sceneFrame: SceneFrame;
  onApplyRxPosition?: (position: Position) => void;
}

export function DevicePanel({
  sceneFrame,
  onApplyRxPosition,
}: DevicePanelProps) {
  const devices = useDeviceStore((state) => state.devices);
  const [coordMode, setCoordMode] = React.useState<CoordMode>('gps');
  const coordinateInputsId = React.useId();
  const currentCoordModeLabel = coordMode === 'gps' ? 'GPS 經緯度' : 'XYZ 座標';
  const nextCoordMode = coordMode === 'gps' ? 'xyz' : 'gps';
  const nextCoordModeLabel = nextCoordMode === 'gps' ? 'GPS 經緯度' : 'XYZ 座標';
  const toggleLabel = `目前為 ${currentCoordModeLabel}，切換為 ${nextCoordModeLabel}`;

  const txDevices = devices.filter((device) => device.role === 'tx');
  const rxDevices = devices.filter((device) => device.role === 'rx');
  const jammerDevices = devices.filter((device) => device.role === 'jammer');

  return (
    <MinPanel as="aside" className="device-panel" title="裝置設定" defaultMinimized>
      <div className="dp-coordinate-toolbar">
        <span>{coordMode === 'gps' ? 'GPS 經緯度' : 'XYZ 座標'}</span>
        <button
          type="button"
          className="dp-coordinate-toggle"
          aria-label={toggleLabel}
          title={toggleLabel}
          aria-pressed={coordMode === 'gps'}
          aria-controls={coordinateInputsId}
          onClick={() => setCoordMode(nextCoordMode)}
        >
          {coordMode === 'gps' ? <GlobeIcon /> : <AxesIcon />}
        </button>
      </div>
      <div id={coordinateInputsId}>
        <Section
          title="TX（發射器）"
          role="tx"
          devices={txDevices}
          coordMode={coordMode}
          sceneFrame={sceneFrame}
          coordinateInputsId={coordinateInputsId}
          canAdd
          showPower
        />
        <Section
          title="RX（UAV）"
          role="rx"
          devices={rxDevices}
          coordMode={coordMode}
          sceneFrame={sceneFrame}
          coordinateInputsId={coordinateInputsId}
          onApplyRxPosition={onApplyRxPosition}
        />
        <Section
          title="Jammer（干擾源）"
          role="jammer"
          devices={jammerDevices}
          coordMode={coordMode}
          sceneFrame={sceneFrame}
          coordinateInputsId={coordinateInputsId}
          canAdd
          showPower
        />
      </div>
    </MinPanel>
  );
}
