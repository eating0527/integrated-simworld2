import React from 'react';
import { useDeviceStore } from '../../store/useDeviceStore';
import type { Device, DeviceRole } from '../../types/device';
import { MinPanel } from './MinPanel';

// ─── Single device row ────────────────────────────────────────────────────────

interface DeviceRowProps {
  device: Device;
  onUpdate: (patch: Partial<Omit<Device, 'id' | 'role'>>) => void;
  onRemove?: () => void;
  showPower: boolean;
  onApplyPosition?: () => void;
  onSaveDefault: () => void;
  onApplyDefault: () => void;
  onZero: () => void;
}

type CoordAxis = 'x' | 'y' | 'z';

function isCompleteNumber(value: string): boolean {
  return /^-?(?:\d+(?:\.\d*)?|\.\d+)$/.test(value.trim());
}

function CoordinateInput({
  axis,
  value,
  onChange,
}: {
  axis: CoordAxis;
  value: number;
  onChange: (axis: CoordAxis, value: number) => void;
}) {
  const [draft, setDraft] = React.useState(String(value));

  React.useEffect(() => {
    setDraft(String(value));
  }, [value]);

  const commit = (next: string) => {
    setDraft(next);
    if (isCompleteNumber(next)) {
      onChange(axis, Number(next));
    }
  };

  return (
    <input
      type="text"
      inputMode="decimal"
      className="dp-input dp-input-sm"
      value={draft}
      onChange={(e) => commit(e.target.value)}
      onBlur={() => setDraft(String(value))}
    />
  );
}

function DeviceRow({
  device,
  onUpdate,
  onRemove,
  showPower,
  onApplyPosition,
  onSaveDefault,
  onApplyDefault,
  onZero,
}: DeviceRowProps) {
  return (
    <div className="dp-device-row">
      {/* Name */}
      <div className="dp-field-row">
        <label className="dp-label">名稱</label>
        <input
          className="dp-input"
          value={device.name}
          onChange={(e) => onUpdate({ name: e.target.value })}
        />
        {onRemove && (
          <button className="dp-btn-remove" onClick={onRemove} title="刪除">
            ✕
          </button>
        )}
      </div>

      {/* Coordinates */}
      <div className="dp-field-row">
        {(['x', 'y', 'z'] as const).map((axis) => (
          <label key={axis} className="dp-coord-label">
            {axis.toUpperCase()}
            <CoordinateInput
              axis={axis}
              value={device[axis]}
              onChange={(nextAxis, value) => onUpdate({ [nextAxis]: value })}
            />
          </label>
        ))}
      </div>

      {/* Power (TX / Jammer only) */}
      {showPower && (
        <div className="dp-field-row">
          <label className="dp-label">功率</label>
          <input
            type="number"
            className="dp-input dp-input-sm"
            value={device.powerDbm ?? 0}
            onChange={(e) => onUpdate({ powerDbm: parseFloat(e.target.value) || 0 })}
          />
          <span className="dp-unit">dBm</span>
        </div>
      )}

      {/* Apply position (RX only) */}
      {onApplyPosition && (
        <div className="dp-field-row">
          <button className="dp-btn-apply" onClick={onApplyPosition}>
            套用位置
          </button>
        </div>
      )}

      <div className="dp-field-row dp-action-row">
        <button className="dp-btn-overwrite" onClick={onSaveDefault}>
          覆寫預設
        </button>
        <button className="dp-btn-apply-default" onClick={onApplyDefault}>
          套用預設
        </button>
        <button className="dp-btn-zero" onClick={onZero}>
          歸零
        </button>
      </div>
    </div>
  );
}

// ─── Section ─────────────────────────────────────────────────────────────────

interface SectionProps {
  title: string;
  role: DeviceRole;
  devices: Device[];
  canAdd?: boolean;
  showPower?: boolean;
  onApplyPosition?: (device: Device) => void;
}

function Section({ title, role, devices, canAdd = false, showPower = false, onApplyPosition }: SectionProps) {
  const {
    addDevice,
    removeDevice,
    updateDevice,
    saveDeviceDefault,
    applyDeviceDefault,
    zeroDevice,
    deviceDefaults,
  } = useDeviceStore();

  const handleApplyDefault = (device: Device) => {
    const savedDefault = deviceDefaults[device.id];
    applyDeviceDefault(device.id);
    if (device.role === 'rx' && savedDefault && onApplyPosition) {
      onApplyPosition({
        ...device,
        x: savedDefault.x,
        y: savedDefault.y,
        z: savedDefault.z,
      });
    }
  };

  const handleZero = (device: Device) => {
    zeroDevice(device.id);
    if (device.role === 'rx' && onApplyPosition) {
      onApplyPosition({ ...device, x: 0, y: 0, z: 0 });
    }
  };

  return (
    <div className="dp-section">
      <div className="dp-section-header">
        <span className="dp-section-title">{title}</span>
        {canAdd && (
          <button className="dp-btn-add" onClick={() => addDevice(role)}>
            + 新增
          </button>
        )}
      </div>
      {devices.map((d) => (
        <DeviceRow
          key={d.id}
          device={d}
          showPower={showPower}
          onUpdate={(patch) => updateDevice(d.id, patch)}
          onRemove={canAdd ? () => removeDevice(d.id) : undefined}
          onApplyPosition={onApplyPosition ? () => onApplyPosition(d) : undefined}
          onSaveDefault={() => saveDeviceDefault(d.id)}
          onApplyDefault={() => handleApplyDefault(d)}
          onZero={() => handleZero(d)}
        />
      ))}
    </div>
  );
}

// ─── Main panel ──────────────────────────────────────────────────────────────

interface DevicePanelProps {
  onApplyRxPosition?: (pos: [number, number, number]) => void;
}

export function DevicePanel({ onApplyRxPosition }: DevicePanelProps = {}) {
  const devices = useDeviceStore((s) => s.devices);

  const txDevices     = devices.filter((d) => d.role === 'tx');
  const rxDevices     = devices.filter((d) => d.role === 'rx');
  const jammerDevices = devices.filter((d) => d.role === 'jammer');

  return (
    <MinPanel as="aside" className="device-panel" title="裝置設定">
      <div className="dp-header">裝置設定</div>

      <Section
        title="TX（發射器）"
        role="tx"
        devices={txDevices}
        canAdd
        showPower
      />
      <Section
        title="RX（UAV）"
        role="rx"
        devices={rxDevices}
        canAdd={false}
        showPower={false}
        onApplyPosition={onApplyRxPosition ? (d) => onApplyRxPosition([d.x, d.y, d.z]) : undefined}
      />
      <Section
        title="Jammer（干擾源）"
        role="jammer"
        devices={jammerDevices}
        canAdd
        showPower
      />
    </MinPanel>
  );
}
