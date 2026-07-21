import assert from 'node:assert/strict';
import { describe, it } from 'vitest';

import { getHeatmapOverlayPlaneConfig } from '../src/components/scene/ISSHeatmapOverlay.tsx';

describe('ISS heatmap overlay plane config', () => {
  it('uses grid bounds for rectangular generated-scene overlays', () => {
    const config = getHeatmapOverlayPlaneConfig({
      frame_id: 'scene-test',
      frame: {
        frame_id: 'scene-test',
        origin: { lat: 24, lon: 121, alt_m: 0 },
        alt_mode: 'amsl',
        extent: { min_e: -300, max_e: 293, min_n: -260, max_n: 270 },
        display_margin_m: 32,
        grid: { rows: 128, cols: 128, pixel_size_e_m: 593 / 128, pixel_size_n_m: 530 / 128 },
      },
      grid: { rows: 128, cols: 128, pixel_size_e_m: 593 / 128, pixel_size_n_m: 530 / 128 },
      areaM: 512,
    });

    assert.equal(config.width, 593);
    assert.equal(config.height, 530);
    assert.deepEqual(config.position, [-3.5, 0.12, -5]);
  });

  it('falls back to the legacy 512m centered square without grid bounds', () => {
    const config = getHeatmapOverlayPlaneConfig({
      frame_id: 'scene-test',
      frame: {
        frame_id: 'scene-test',
        origin: { lat: 24, lon: 121, alt_m: 0 },
        alt_mode: 'amsl',
        extent: { min_e: -256, max_e: 256, min_n: -256, max_n: 256 },
        display_margin_m: 32,
        grid: { rows: 128, cols: 128, pixel_size_e_m: 4, pixel_size_n_m: 4 },
      },
      grid: { rows: 128, cols: 128, pixel_size_e_m: 4, pixel_size_n_m: 4 },
      areaM: 512,
    });

    assert.equal(config.width, 512);
    assert.equal(config.height, 512);
    assert.deepEqual(config.position, [0, 0.12, 0]);
  });
});
