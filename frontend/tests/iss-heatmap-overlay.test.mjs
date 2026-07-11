import assert from 'node:assert/strict';
import { describe, it } from 'vitest';

import { getHeatmapOverlayPlaneConfig } from '../src/components/scene/ISSHeatmapOverlay.tsx';

describe('ISS heatmap overlay plane config', () => {
  it('uses grid bounds for rectangular generated-scene overlays', () => {
    const config = getHeatmapOverlayPlaneConfig({
      areaM: 512,
      gridBounds: {
        min_x: -300,
        max_x: 293,
        min_y: -260,
        max_y: 270,
        pixel_size_x_m: 593 / 128,
        pixel_size_y_m: 530 / 128,
      },
    });

    assert.equal(config.width, 593);
    assert.equal(config.height, 530);
    assert.deepEqual(config.position, [-3.5, 0.12, -5]);
  });

  it('falls back to the legacy 512m centered square without grid bounds', () => {
    const config = getHeatmapOverlayPlaneConfig({ areaM: 512 });

    assert.equal(config.width, 512);
    assert.equal(config.height, 512);
    assert.deepEqual(config.position, [0, 0.12, 0]);
  });
});
