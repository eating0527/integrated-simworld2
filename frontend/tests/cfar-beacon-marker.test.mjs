import assert from 'node:assert/strict';
import { describe, it } from 'vitest';

import { getCFARBeaconVisualConfig } from '../src/components/scene/CFARBeaconMarker.tsx';

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
});
