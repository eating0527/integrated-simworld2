import assert from 'node:assert/strict';
import { describe, it } from 'vitest';

import { getIssNoiseColor, getIssRouteLinePoints } from '../src/components/scene/ISSRouteOverlay.tsx';

describe('ISS route overlay helpers', () => {
  it('uses all or aligned route points and filters invalid coordinates', () => {
    const overlay = {
      routeMode: 'all',
      routePoints: [
        { lat: 0, lon: 0, alt: 2, row: 0, col: 0, world_x: 10, world_z: 20 },
        { lat: 0, lon: 0, alt: 9, row: 0, col: 0, world_x: Number.NaN, world_z: 30 },
        { lat: 0, lon: 0, alt: 8, row: 0, col: 0, world_x: 30, world_z: 40 },
      ],
      alignedPoints: [
        { lat: 0, lon: 0, alt: 1, row: 0, col: 0, world_x: 50, world_z: 60 },
      ],
      samplePoints: [],
    };

    assert.deepEqual(getIssRouteLinePoints(overlay), [
      [10, 4, 20],
      [30, 8, 40],
    ]);

    assert.deepEqual(getIssRouteLinePoints({ ...overlay, routeMode: 'aligned' }), [
      [50, 4, 60],
    ]);
  });

  it('maps noise floor from blue at low power to red at high power', () => {
    assert.equal(getIssNoiseColor(-90), '#000080');
    assert.equal(getIssNoiseColor(-15), '#800000');
    assert.equal(getIssNoiseColor(-120), getIssNoiseColor(-90));
    assert.equal(getIssNoiseColor(20), getIssNoiseColor(-15));
    assert.match(getIssNoiseColor(-52.5), /^#[0-9a-f]{6}$/);
  });

  it('falls back to low power color for non-finite noise floor', () => {
    assert.equal(getIssNoiseColor(undefined), '#000080');
    assert.equal(getIssNoiseColor(Number.NaN), '#000080');
    assert.equal(getIssNoiseColor(Number.POSITIVE_INFINITY), '#000080');
  });

  it('uses minimum height for non-finite altitude', () => {
    const overlay = {
      routeMode: 'all',
      routePoints: [
        { lat: 0, lon: 0, alt: Number.POSITIVE_INFINITY, row: 0, col: 0, world_x: 10, world_z: 20 },
      ],
      alignedPoints: [],
      samplePoints: [],
    };

    assert.deepEqual(getIssRouteLinePoints(overlay), [[10, 4, 20]]);
  });

  it('keeps fewer than two valid line points for the renderer to skip', () => {
    const overlay = {
      routeMode: 'all',
      routePoints: [
        { lat: 0, lon: 0, alt: 8, row: 0, col: 0, world_x: 10, world_z: 20 },
        { lat: 0, lon: 0, alt: 8, row: 0, col: 0, world_x: Number.NaN, world_z: 20 },
      ],
      alignedPoints: [],
      samplePoints: [],
    };

    assert.equal(getIssRouteLinePoints(overlay).length, 1);
  });
});
