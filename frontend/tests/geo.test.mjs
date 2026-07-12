import assert from 'node:assert/strict';
import { describe, it } from 'vitest';

import {
  enuToGps,
  enuToGrid,
  enuToThree,
  gpsToEnu,
  threeToEnu,
} from '../src/utils/geo.ts';

const frame = {
  frame_id: 'scene-test',
  origin: { lat: 24.943476, lon: 121.370054, alt_m: 100 },
  alt_mode: 'amsl',
  extent: { min_e: -256, max_e: 256, min_n: -256, max_n: 256 },
  display_margin_m: 32,
  grid: { rows: 128, cols: 128, pixel_size_e_m: 4, pixel_size_n_m: 4 },
};

describe('geo utilities', () => {
  it('round-trips GPS through ENU without changing altitude mode', () => {
    const input = { lat: 24.945, lon: 121.372, alt: 125 };
    const enu = gpsToEnu(input, frame, 'amsl');
    const gps = enuToGps(enu, frame, 'amsl');

    assert.ok(Math.abs(gps.lat - input.lat) < 1e-10);
    assert.ok(Math.abs(gps.lon - input.lon) < 1e-10);
    assert.equal(gps.alt, input.alt);
    assert.equal(enu.up_m, 25);
  });

  it('uses relative altitude as U without subtracting the origin altitude', () => {
    assert.deepEqual(gpsToEnu({ lat: frame.origin.lat, lon: frame.origin.lon, alt: 25 }, frame, 'relative'), {
      east_m: 0,
      north_m: 0,
      up_m: 25,
    });
  });

  it('maps ENU to Three as x=E, y=U, z=-N and back', () => {
    const three = enuToThree({ east_m: 10, north_m: 20, up_m: 30 });
    assert.deepEqual(three, [10, 30, -20]);
    assert.deepEqual(threeToEnu(three), { east_m: 10, north_m: 20, up_m: 30 });
  });

  it('keeps true coordinates inside the 32m display margin without clamping', () => {
    assert.deepEqual(enuToGrid({ east_m: 270, north_m: 0, up_m: 7 }, frame), {
      row: null,
      col: null,
      inside_extent: false,
      displayable: true,
    });
    assert.equal(enuToGrid({ east_m: 288, north_m: 0, up_m: 7 }, frame).displayable, false);
  });

  it('clamps the inclusive south/west edges to the last grid cell', () => {
    assert.deepEqual(enuToGrid({ east_m: -256, north_m: -256, up_m: 0 }, frame), {
      row: 127,
      col: 0,
      inside_extent: true,
      displayable: true,
    });
  });
});
