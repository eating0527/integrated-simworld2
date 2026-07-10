import assert from 'node:assert/strict';
import { describe, it } from 'vitest';

import {
  GPS_REPLAY_BASE_POINTS_PER_SECOND,
  getGpsReplayIntervalMs,
  parseGpsReplayCsv,
} from '../src/utils/gpsReplay.ts';

describe('GPS replay utilities', () => {
  it('sorts GPS CSV rows by earliest timestamp', () => {
    const points = parseGpsReplayCsv(`time_stamp,lat,lon,alt
2026-05-11T16:52:17.302053,24.3,121.3,40
2026-05-11T16:52:16.306518,24.1,121.1,20
2026-05-11T16:52:16.803713,24.2,121.2,30
`);

    assert.deepEqual(points.map((point) => point.lat), [24.1, 24.2, 24.3]);
    assert.deepEqual(points.map((point) => point.alt), [20, 30, 40]);
  });

  it('keeps replay timing at 2 points per second for 1x', () => {
    assert.equal(GPS_REPLAY_BASE_POINTS_PER_SECOND, 2);
    assert.equal(getGpsReplayIntervalMs(1), 500);
    assert.equal(getGpsReplayIntervalMs(2), 250);
    assert.equal(getGpsReplayIntervalMs(5), 100);
  });
});
