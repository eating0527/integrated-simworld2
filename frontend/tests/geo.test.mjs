import assert from 'node:assert/strict';
import { describe, it } from 'vitest';

import { worldXZToLatLon } from '../src/utils/geo.ts';

describe('geo utilities', () => {
  it('converts scene world XZ coordinates back to GPS coordinates', () => {
    const origin = { lat: 24.943476, lon: 121.370054, alt: 0 };

    const gps = worldXZToLatLon(10, -20, origin);

    assert.equal(Number.isFinite(gps.lat), true);
    assert.equal(Number.isFinite(gps.lon), true);
    assert.equal(gps.alt, 0);
    assert.ok(gps.lat > origin.lat);
    assert.ok(gps.lon > origin.lon);
  });
});
