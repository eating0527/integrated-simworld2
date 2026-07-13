import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { useDeviceStore } from '../../store/useDeviceStore';
import { createSceneFrame } from '../../types/sceneFrame';
import { enuToGps, enuToThree, gpsToEnu, threeToEnu } from '../../utils/geo';
import { DevicePanel } from './DevicePanel';

const frame = createSceneFrame('scene-test', { lat: 24, lon: 121, alt_m: 100 });
const labels = { lat: '\u7DEF\u5EA6', lon: '\u7D93\u5EA6', alt: '\u9AD8\u5EA6' };
const applyPositionLabel = '\u5957\u7528\u4F4D\u7F6E';
const switchToXyz = /\u5207\u63DB\u70BA XYZ/;
const switchToGps = /\u5207\u63DB\u70BA GPS/;

const devices = [
  { id: 'dev-tx-0', name: 'tx-0', role: 'tx' as const, x: -75, y: 0, z: 75, powerDbm: 60 },
  { id: 'dev-rx-0', name: 'rx-0', role: 'rx' as const, x: -30, y: 10, z: 175 },
  { id: 'dev-jam-0', name: 'jam-0', role: 'jammer' as const, x: -150, y: 0, z: 170, powerDbm: 60 },
];

function renderPanel(onApplyRxPosition = vi.fn()) {
  render(<DevicePanel sceneFrame={frame} onApplyRxPosition={onApplyRxPosition} />);
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
  useDeviceStore.setState({ devices });
});

describe('DevicePanel coordinate modes', () => {
  it('applies GPS positions to TX, RX, and Jammer canonical xyz', async () => {
    renderPanel();
    const user = await openPanel();
    const positions = [
      ['dev-tx-0', 'tx-0', { lat: 24.001, lon: 121.001, alt: 110 }],
      ['dev-rx-0', 'rx-0', { lat: 23.999, lon: 120.999, alt: 90 }],
      ['dev-jam-0', 'jam-0', { lat: 24.0005, lon: 121.0005, alt: 105 }],
    ] as const;

    for (const [id, name, gps] of positions) {
      const row = getRow(name);
      await fillGps(user, row, name, gps);
      await user.click(within(row).getByRole('button', { name: applyPositionLabel }));
      const expected = enuToThree(gpsToEnu(gps, frame, frame.alt_mode));

      expect(getDevice(id)).toMatchObject({
        x: expected[0],
        y: expected[1],
        z: expected[2],
      });
    }
  });

  it('calls onApplyRxPosition when RX is applied', async () => {
    const onApplyRxPosition = vi.fn();
    renderPanel(onApplyRxPosition);
    const user = await openPanel();
    const row = getRow('rx-0');

    await user.click(within(row).getByRole('button', { name: applyPositionLabel }));

    const rx = getDevice('dev-rx-0');
    expect(onApplyRxPosition).toHaveBeenCalledWith([rx.x, rx.y, rx.z]);
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
    await user.click(screen.getByRole('button', { name: switchToXyz }));

    expect(within(row).getByRole('textbox', { name: 'X tx-0' })).toHaveValue('-75');
    expect(within(row).getByRole('textbox', { name: 'Y tx-0' })).toHaveValue('0');
    expect(within(row).getByRole('textbox', { name: 'Z tx-0' })).toHaveValue('75');

    const x = within(row).getByRole('textbox', { name: 'X tx-0' });
    await user.clear(x);
    await user.type(x, '123');
    await user.click(screen.getByRole('button', { name: switchToGps }));
    expect(within(row).getByRole('textbox', { name: `${labels.lat} tx-0` })).toHaveValue(String(expectedGps.lat));
    expect(within(row).getByRole('textbox', { name: `${labels.lon} tx-0` })).toHaveValue(String(expectedGps.lon));
    expect(within(row).getByRole('textbox', { name: `${labels.alt} tx-0` })).toHaveValue(String(expectedGps.alt));
  });

  it('rebinds GPS and xyz from the same applied canonical position', async () => {
    renderPanel();
    const user = await openPanel();
    const row = getRow('tx-0');
    const device = getDevice('dev-tx-0');
    const expectedGps = enuToGps(threeToEnu([device.x, device.y, device.z]), frame, frame.alt_mode);

    await user.click(screen.getByRole('button', { name: switchToXyz }));
    expect(within(row).getByRole('textbox', { name: 'X tx-0' })).toHaveValue(String(device.x));
    expect(within(row).getByRole('textbox', { name: 'Y tx-0' })).toHaveValue(String(device.y));
    expect(within(row).getByRole('textbox', { name: 'Z tx-0' })).toHaveValue(String(device.z));
    await user.click(screen.getByRole('button', { name: switchToGps }));

    expect(within(row).getByRole('textbox', { name: `${labels.lat} tx-0` })).toHaveValue(String(expectedGps.lat));
    expect(within(row).getByRole('textbox', { name: `${labels.lon} tx-0` })).toHaveValue(String(expectedGps.lon));
    expect(within(row).getByRole('textbox', { name: `${labels.alt} tx-0` })).toHaveValue(String(expectedGps.alt));
    await user.click(screen.getByRole('button', { name: switchToXyz }));
    expect(within(row).getByRole('textbox', { name: 'X tx-0' })).toHaveValue(String(device.x));
    expect(within(row).getByRole('textbox', { name: 'Y tx-0' })).toHaveValue(String(device.y));
    expect(within(row).getByRole('textbox', { name: 'Z tx-0' })).toHaveValue(String(device.z));
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
    renderPanel();
    const user = await openPanel();
    const row = getRow('tx-0');
    await user.click(screen.getByRole('button', { name: switchToXyz }));
    const apply = within(row).getByRole('button', { name: applyPositionLabel });
    const x = within(row).getByRole('textbox', { name: 'X tx-0' });
    const z = within(row).getByRole('textbox', { name: 'Z tx-0' });

    await user.clear(x);
    await user.type(x, '255.9');
    await user.clear(z);
    await user.type(z, '-255.9');
    await user.click(apply);
    expect(getDevice('dev-tx-0')).toMatchObject({ x: 255.9, z: -255.9 });

    await user.clear(x);
    await user.type(x, '256');
    await user.click(apply);
    expect(getDevice('dev-tx-0')).toMatchObject({ x: 255.9, z: -255.9 });

    await user.clear(x);
    await user.type(x, '255.9');
    await user.clear(z);
    await user.type(z, '-256');
    await user.click(apply);
    expect(getDevice('dev-tx-0')).toMatchObject({ x: 255.9, z: -255.9 });
  });

  it('exposes a keyboard-operable coordinate mode button to assistive technology', async () => {
    renderPanel();
    await openPanel();
    const toggle = screen.getByRole('button', { name: switchToXyz });
    const controlsId = toggle.getAttribute('aria-controls');

    expect(toggle).toHaveAttribute('aria-label');
    expect(toggle).toHaveAttribute('aria-pressed', 'true');
    expect(controlsId).toBeTruthy();
    expect(document.getElementById(controlsId!)).toBeInTheDocument();

    toggle.focus();
    await userEvent.setup().keyboard('{Enter}');
    expect(toggle).toHaveAttribute('aria-pressed', 'false');
    expect(screen.getByRole('textbox', { name: 'X tx-0' })).toBeInTheDocument();
  });
});
