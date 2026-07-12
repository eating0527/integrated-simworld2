import assert from 'node:assert/strict';
import { describe, it } from 'vitest';

import { getIssNoiseColor, getIssRouteLinePoints } from '../src/components/scene/ISSRouteOverlay.tsx';

describe('ISS route overlay helpers', () => {
  it('uses all or aligned route points and filters invalid coordinates', () => {
    const overlay = {
      routeMode: 'all',
      routePoints: [
        { lat: 0, lon: 0, alt: 2, alt_mode: 'relative', frame_id: 'scene-test', enu: { east_m: 10, north_m: 20, up_m: 2 }, grid: { row: 0, col: 0, inside_extent: true, displayable: true } },
        { lat: 0, lon: 0, alt: 9, alt_mode: 'relative', frame_id: 'scene-test', enu: { east_m: Number.NaN, north_m: 30, up_m: 9 }, grid: { row: 0, col: 0, inside_extent: true, displayable: true } },
        { lat: 0, lon: 0, alt: 8, alt_mode: 'relative', frame_id: 'scene-test', enu: { east_m: 30, north_m: 40, up_m: 8 }, grid: { row: 0, col: 0, inside_extent: true, displayable: true } },
      ],
      alignedPoints: [
        { lat: 0, lon: 0, alt: 1, alt_mode: 'relative', frame_id: 'scene-test', enu: { east_m: 50, north_m: 60, up_m: 1 }, grid: { row: 0, col: 0, inside_extent: true, displayable: true } },
      ],
      samplePoints: [],
    };

    assert.deepEqual(getIssRouteLinePoints(overlay), [
      [10, 2, -20],
      [30, 8, -40],
    ]);

    assert.deepEqual(getIssRouteLinePoints({ ...overlay, routeMode: 'aligned' }), [
      [50, 1, -60],
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

  it('filters non-finite ENU coordinates', () => {
    const overlay = {
      routeMode: 'all',
      routePoints: [
        { lat: 0, lon: 0, alt: Number.POSITIVE_INFINITY, alt_mode: 'relative', frame_id: 'scene-test', enu: { east_m: 10, north_m: 20, up_m: Number.POSITIVE_INFINITY }, grid: { row: 0, col: 0, inside_extent: true, displayable: true } },
      ],
      alignedPoints: [],
      samplePoints: [],
    };

    assert.deepEqual(getIssRouteLinePoints(overlay), []);
  });

  it('keeps fewer than two valid line points for the renderer to skip', () => {
    const overlay = {
      routeMode: 'all',
      routePoints: [
        { lat: 0, lon: 0, alt: 8, alt_mode: 'relative', frame_id: 'scene-test', enu: { east_m: 10, north_m: 20, up_m: 8 }, grid: { row: 0, col: 0, inside_extent: true, displayable: true } },
        { lat: 0, lon: 0, alt: 8, alt_mode: 'relative', frame_id: 'scene-test', enu: { east_m: Number.NaN, north_m: 20, up_m: 8 }, grid: { row: 0, col: 0, inside_extent: true, displayable: true } },
      ],
      alignedPoints: [],
      samplePoints: [],
    };

    assert.equal(getIssRouteLinePoints(overlay).length, 1);
  });
});
