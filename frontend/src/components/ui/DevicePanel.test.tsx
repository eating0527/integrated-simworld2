import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { useDeviceStore } from '../../store/useDeviceStore';
import { createSceneFrame } from '../../types/sceneFrame';
import { getCurrentDevicePayload } from '../../utils/devicePayload';
import { enuToGps, enuToThree, gpsToEnu, threeToEnu } from '../../utils/geo';
import { DevicePanel } from './DevicePanel';

const frame = createSceneFrame('scene-test', { lat: 24, lon: 121, alt_m: 100 });
const labels = { lat: '\u7DEF\u5EA6', lon: '\u7D93\u5EA6', alt: '\u9AD8\u5EA6' };
const applyPositionLabel = '\u5957\u7528\u4F4D\u7F6E';
const switchToXyzLabel = '\u76EE\u524D\u70BA GPS \u7D93\u7DEF\u5EA6\uFF0C\u5207\u63DB\u70BA XYZ \u5EA7\u6A19';
const switchToGpsLabel = '\u76EE\u524D\u70BA XYZ \u5EA7\u6A19\uFF0C\u5207\u63DB\u70BA GPS \u7D93\u7DEF\u5EA6';

const devices = [
  { id: 'dev-tx-0', name: 'tx-0', role: 'tx' as const, x: -75, y: 0, z: 75, powerDbm: 60 },
  { id: 'dev-rx-0', name: 'rx-0', role: 'rx' as const, x: -30, y: 10, z: 175 },
  { id: 'dev-jam-0', name: 'jam-0', role: 'jammer' as const, x: -150, y: 0, z: 170, powerDbm: 60 },
];

function renderPanel(onApplyRxPosition = vi.fn(), sceneFrame = frame) {
  render(<DevicePanel sceneFrame={sceneFrame} onApplyRxPosition={onApplyRxPosition} />);
}

async function openPanel() {
  const user = userEvent.setup();
  await user.click(screen.getByRole('button', { name: /restore/i }));
  return user;
}

function getRow(name: string) {
  return screen.getByDisplayValue(name).closest('.dp-device-row')!;
}

async function fillGps(
  user: ReturnType<typeof userEvent.setup>,
  row: HTMLElement,
  deviceName: string,
  gps: { lat: number; lon: number; alt: number },
) {
  for (const [label, value] of [
    [labels.lat, gps.lat],
    [labels.lon, gps.lon],
    [labels.alt, gps.alt],
  ] as const) {
    const input = within(row).getByRole('textbox', { name: `${label} ${deviceName}` });
    await user.clear(input);
    await user.type(input, String(value));
  }
}

function getDevice(id: string) {
  return useDeviceStore.getState().devices.find((device) => device.id === id)!;
}

beforeEach(() => {
  useDeviceStore.setState({
    devices,
    modelVisible: { tx: true, rx: true, jammer: true },
  });
});

describe('DevicePanel 3D visibility', () => {
  it.each([
    ['TX', 'tx'],
    ['RX', 'rx'],
    ['Jam', 'jammer'],
  ] as const)('toggles every %s model without removing simulation devices', async (label, role) => {
    renderPanel();
    const user = await openPanel();
    const before = getCurrentDevicePayload(frame);
    const toggle = screen.getByRole('switch', { name: `顯示 ${label} 3D 模型` });

    await user.click(toggle);

    expect(toggle).not.toBeChecked();
    expect(useDeviceStore.getState().modelVisible[role]).toBe(false);
    expect(getCurrentDevicePayload(frame)).toEqual(before);
  });
});

describe('DevicePanel coordinate modes', () => {
  it('applies GPS positions to TX, RX, and Jammer canonical xyz', async () => {
    const onApplyRxPosition = vi.fn();
    renderPanel(onApplyRxPosition);
    const user = await openPanel();
    const positions = [
      ['dev-tx-0', 'tx-0', { lat: 24.001, lon: 121.001, alt: 110 }],
      ['dev-rx-0', 'rx-0', { lat: 23.999, lon: 120.999, alt: 90 }],
      ['dev-jam-0', 'jam-0', { lat: 24.0005, lon: 121.0005, alt: 105 }],
    ] as const;

    for (const [id, name, gps] of positions) {
      const row = getRow(name);
      const before = getDevice(id);
      const callbackCount = onApplyRxPosition.mock.calls.length;
      await fillGps(user, row, name, gps);
      expect(getDevice(id)).toEqual(before);
      expect(onApplyRxPosition).toHaveBeenCalledTimes(callbackCount);
      await user.click(within(row).getByRole('button', { name: applyPositionLabel }));
      const expected = enuToThree(gpsToEnu(gps, frame, frame.alt_mode));

      expect(getDevice(id)).toMatchObject({
        x: expected[0],
        y: expected[1],
        z: expected[2],
      });
      if (id === 'dev-tx-0') expect(onApplyRxPosition).toHaveBeenCalledTimes(0);
      if (id === 'dev-rx-0') expect(onApplyRxPosition).toHaveBeenCalledTimes(1);
      if (id === 'dev-jam-0') expect(onApplyRxPosition).toHaveBeenCalledTimes(1);
    }
  });

  it('calls onApplyRxPosition when RX is applied', async () => {
    const onApplyRxPosition = vi.fn();
    renderPanel(onApplyRxPosition);
    const user = await openPanel();
    const row = getRow('rx-0');
    const initialRx = getDevice('dev-rx-0');
    const initialGps = enuToGps(threeToEnu([initialRx.x, initialRx.y, initialRx.z]), frame, frame.alt_mode);
    const updatedGps = { ...initialGps, lat: initialGps.lat + 0.001 };
    const expected = enuToThree(gpsToEnu(updatedGps, frame, frame.alt_mode));

    const latitude = within(row).getByRole('textbox', { name: `${labels.lat} rx-0` });
    await user.clear(latitude);
    await user.type(latitude, String(updatedGps.lat));
    expect(getDevice('dev-rx-0')).toMatchObject({ x: initialRx.x, y: initialRx.y, z: initialRx.z });
    expect(onApplyRxPosition).not.toHaveBeenCalled();
    await user.click(within(row).getByRole('button', { name: applyPositionLabel }));

    const rx = getDevice('dev-rx-0');
    expect(rx).toMatchObject({ x: expected[0], y: expected[1], z: expected[2] });
    expect(onApplyRxPosition).toHaveBeenCalledTimes(1);
    expect(onApplyRxPosition).toHaveBeenCalledWith(expected);
  });

  it('discards an unsubmitted draft when switching from GPS to xyz', async () => {
    renderPanel();
    const user = await openPanel();
    const row = getRow('tx-0');
    const latitude = within(row).getByRole('textbox', { name: `${labels.lat} tx-0` });
    const device = getDevice('dev-tx-0');
    const expectedGps = enuToGps(threeToEnu([device.x, device.y, device.z]), frame, frame.alt_mode);

    await user.clear(latitude);
    await user.type(latitude, '24.1');
    await user.click(screen.getByRole('button', { name: switchToXyzLabel }));

    expect(within(row).getByRole('textbox', { name: 'X tx-0' })).toHaveValue('-75');
    expect(within(row).getByRole('textbox', { name: 'Y tx-0' })).toHaveValue('0');
    expect(within(row).getByRole('textbox', { name: 'Z tx-0' })).toHaveValue('75');

    const x = within(row).getByRole('textbox', { name: 'X tx-0' });
    await user.clear(x);
    await user.type(x, '123');
    await user.click(screen.getByRole('button', { name: switchToGpsLabel }));
    expect(within(row).getByRole('textbox', { name: `${labels.lat} tx-0` })).toHaveValue(String(expectedGps.lat));
    expect(within(row).getByRole('textbox', { name: `${labels.lon} tx-0` })).toHaveValue(String(expectedGps.lon));
    expect(within(row).getByRole('textbox', { name: `${labels.alt} tx-0` })).toHaveValue(String(expectedGps.alt));
  });

  it('keeps RX canonical xyz and callback unchanged until a valid xyz draft is applied', async () => {
    const onApplyRxPosition = vi.fn();
    renderPanel(onApplyRxPosition);
    const user = await openPanel();
    const row = getRow('rx-0');
    const before = getDevice('dev-rx-0');
    const apply = within(row).getByRole('button', { name: applyPositionLabel });

    await user.click(screen.getByRole('button', { name: switchToXyzLabel }));
    for (const [axis, value] of [['X', '-29'], ['Y', '10'], ['Z', '175']] as const) {
      const input = within(row).getByRole('textbox', { name: `${axis} rx-0` });
      await user.clear(input);
      await user.type(input, value);
    }

    expect(apply).not.toBeDisabled();
    expect(getDevice('dev-rx-0')).toEqual(before);
    expect(onApplyRxPosition).not.toHaveBeenCalled();

    await user.click(apply);
    expect(getDevice('dev-rx-0')).toMatchObject({ x: -29, y: 10, z: 175 });
    expect(onApplyRxPosition).toHaveBeenCalledWith([-29, 10, 175]);
  });

  it('rebinds GPS and xyz from a newly applied canonical position without drift', async () => {
    renderPanel();
    const user = await openPanel();
    const row = getRow('tx-0');
    const newGps = { lat: 24.0008, lon: 121.0007, alt: 108 };
    await fillGps(user, row, 'tx-0', newGps);
    await user.click(within(row).getByRole('button', { name: applyPositionLabel }));

    const canonical = getDevice('dev-tx-0');
    const expectedCanonical = enuToThree(gpsToEnu(newGps, frame, frame.alt_mode));
    const expectedGps = enuToGps(threeToEnu([canonical.x, canonical.y, canonical.z]), frame, frame.alt_mode);
    expect(canonical).toMatchObject({ x: expectedCanonical[0], y: expectedCanonical[1], z: expectedCanonical[2] });

    await user.click(screen.getByRole('button', { name: switchToXyzLabel }));
    expect(within(row).getByRole('textbox', { name: 'X tx-0' })).toHaveValue(String(canonical.x));
    expect(within(row).getByRole('textbox', { name: 'Y tx-0' })).toHaveValue(String(canonical.y));
    expect(within(row).getByRole('textbox', { name: 'Z tx-0' })).toHaveValue(String(canonical.z));
    await user.click(screen.getByRole('button', { name: switchToGpsLabel }));

    expect(within(row).getByRole('textbox', { name: `${labels.lat} tx-0` })).toHaveValue(String(expectedGps.lat));
    expect(within(row).getByRole('textbox', { name: `${labels.lon} tx-0` })).toHaveValue(String(expectedGps.lon));
    expect(within(row).getByRole('textbox', { name: `${labels.alt} tx-0` })).toHaveValue(String(expectedGps.alt));
    await user.click(screen.getByRole('button', { name: switchToXyzLabel }));
    expect(within(row).getByRole('textbox', { name: 'X tx-0' })).toHaveValue(String(canonical.x));
    expect(within(row).getByRole('textbox', { name: 'Y tx-0' })).toHaveValue(String(canonical.y));
    expect(within(row).getByRole('textbox', { name: 'Z tx-0' })).toHaveValue(String(canonical.z));
  });

  it('does not update the store for incomplete GPS input', async () => {
    renderPanel();
    const user = await openPanel();
    const row = getRow('tx-0');
    const before = getDevice('dev-tx-0');

    await user.clear(within(row).getByRole('textbox', { name: `${labels.lat} tx-0` }));
    expect(within(row).getByRole('button', { name: applyPositionLabel })).toBeDisabled();
    expect(getDevice('dev-tx-0')).toEqual(before);
  });

  it('applies inside extent and rejects east and north exclusive maximums', async () => {
    const extentFrame = {
      ...createSceneFrame('scene-extent-test', { lat: 24, lon: 121, alt_m: 100 }),
      extent: { min_e: -32, max_e: 48, min_n: -24, max_n: 40 },
    };
    renderPanel(vi.fn(), extentFrame);
    const user = await openPanel();
    const row = getRow('tx-0');
    await user.click(screen.getByRole('button', { name: switchToXyzLabel }));
    const apply = within(row).getByRole('button', { name: applyPositionLabel });
    const x = within(row).getByRole('textbox', { name: 'X tx-0' });
    const z = within(row).getByRole('textbox', { name: 'Z tx-0' });

    await user.clear(x);
    await user.type(x, '-32');
    await user.clear(z);
    await user.type(z, '24');
    await user.click(apply);
    expect(getDevice('dev-tx-0')).toMatchObject({ x: -32, z: 24 });

    await user.clear(x);
    await user.type(x, '48');
    await user.click(apply);
    expect(getDevice('dev-tx-0')).toMatchObject({ x: -32, z: 24 });

    await user.clear(x);
    await user.type(x, '-32');
    await user.clear(z);
    await user.type(z, '-40');
    await user.click(apply);
    expect(getDevice('dev-tx-0')).toMatchObject({ x: -32, z: 24 });
  });

  it('validates GPS drafts against a non-default scene extent', async () => {
    const gpsFrame = {
      ...createSceneFrame('scene-gps-extent-test', { lat: 25, lon: 120, alt_m: 50 }),
      extent: { min_e: -20, max_e: 30, min_n: -10, max_n: 25 },
    };
    const insideGps = enuToGps({ east_m: 12, north_m: 10, up_m: 7 }, gpsFrame, gpsFrame.alt_mode);
    const outsideGps = enuToGps({ east_m: 31, north_m: 10, up_m: 7 }, gpsFrame, gpsFrame.alt_mode);

    renderPanel(vi.fn(), gpsFrame);
    const user = await openPanel();
    const row = getRow('tx-0');
    const apply = within(row).getByRole('button', { name: applyPositionLabel });

    await fillGps(user, row, 'tx-0', insideGps);
    await user.click(apply);
    const expectedInside = enuToThree(gpsToEnu(insideGps, gpsFrame, gpsFrame.alt_mode));
    const applied = getDevice('dev-tx-0');
    expect(applied).toMatchObject({
      x: expectedInside[0],
      y: expectedInside[1],
      z: expectedInside[2],
    });

    await fillGps(user, row, 'tx-0', outsideGps);
    await user.click(apply);
    expect(getDevice('dev-tx-0')).toEqual(applied);
  });

  it('exposes a keyboard-operable coordinate mode button to assistive technology', async () => {
    renderPanel();
    const user = await openPanel();
    const toggle = screen.getByRole('button', { name: switchToXyzLabel });
    const controlsId = toggle.getAttribute('aria-controls');

    expect(toggle).toHaveAttribute('aria-label', switchToXyzLabel);
    expect(toggle).toHaveAttribute('aria-pressed', 'true');
    expect(controlsId).toBeTruthy();
    expect(document.getElementById(controlsId!)).toBeInTheDocument();

    toggle.focus();
    await user.keyboard('{Enter}');
    expect(toggle).toHaveAttribute('aria-pressed', 'false');
    expect(toggle).toHaveAttribute('aria-label', switchToGpsLabel);
    expect(screen.getByRole('button', { name: switchToGpsLabel })).toBe(toggle);
    expect(screen.getByRole('textbox', { name: 'X tx-0' })).toBeInTheDocument();
  });
});
