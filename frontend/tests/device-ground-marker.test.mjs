import assert from 'node:assert/strict';
import { describe, it } from 'vitest';

import {
  getDeviceGroundMarkerVisualConfig,
} from '../src/components/scene/DeviceGroundMarker.tsx';

describe('device ground marker visual config', () => {
  it('uses blue for TX and green for Jammer', () => {
    assert.equal(getDeviceGroundMarkerVisualConfig('tx').color, '#2ea8ff');
    assert.equal(getDeviceGroundMarkerVisualConfig('jammer').color, '#39e66d');
  });

  it('keeps a fixed circular footprint for both roles', () => {
    const tx = getDeviceGroundMarkerVisualConfig('tx');
    const jammer = getDeviceGroundMarkerVisualConfig('jammer');

    assert.equal(tx.diameter, jammer.diameter);
    assert.equal(tx.radius, jammer.radius);
    assert.ok(tx.diameter > 0);
    assert.equal(tx.radius, tx.diameter / 2);
  });

  it('raises the ring slightly above the ground to avoid z-fighting', () => {
    const config = getDeviceGroundMarkerVisualConfig('tx');

    assert.ok(config.ringY > 0);
    assert.ok(config.fillY > 0);
    assert.ok(config.ringY > config.fillY);
  });
});
