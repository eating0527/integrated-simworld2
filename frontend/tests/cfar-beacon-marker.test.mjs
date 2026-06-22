import assert from 'node:assert/strict';
import { describe, it } from 'vitest';

import {
  getCFARBeaconLabelVisualConfig,
  getCFARBeaconVisualConfig,
} from '../src/components/scene/CFARBeaconMarker.tsx';

describe('CFAR beacon marker visual config', () => {
  it('uses the same beacon diameter for all cluster sizes', () => {
    const small = getCFARBeaconVisualConfig({ size: 1 });
    const large = getCFARBeaconVisualConfig({ size: 400 });

    assert.equal(small.diameter, large.diameter);
    assert.equal(small.radius, large.radius);
  });

  it('uses a tall sky-reaching beam for recognizability', () => {
    const config = getCFARBeaconVisualConfig({ size: 9 });

    assert.ok(config.height >= 900);
    assert.ok(config.height / config.diameter >= 40);
  });

  it('uses a larger label box for readable interference map beacon text', () => {
    const config = getCFARBeaconLabelVisualConfig();

    assert.ok(config.minWidth >= 260);
    assert.ok(config.fontSize >= 12);
    assert.match(config.padding, /^8px\s+12px$/);
  });
});
