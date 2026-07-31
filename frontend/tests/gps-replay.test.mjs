import assert from 'node:assert/strict';
import { describe, it } from 'vitest';

import {
  GPS_REPLAY_BASE_POINTS_PER_SECOND,
  getGpsReplayIntervalMs,
  parseGpsReplayCsv,
} from '../src/utils/gpsReplay.ts';

describe('GPS replay utilities', () => {
  it('parses noise-compatible timestamps with an explicit timezone offset', () => {
    const points = parseGpsReplayCsv(`time_stamp,lat,lon,alt,alt_mode
2026-07-31T15:54:33.458000+08:00,24.8503433,120.9281001,1.584,relative
2026-07-31T15:54:32.481000+08:00,24.8503435,120.9280999,1.585,relative
`);

    assert.equal(points.length, 2);
    assert.deepEqual(points.map((point) => point.lat), [24.8503435, 24.8503433]);
    assert.deepEqual(points.map((point) => point.altMode), ['relative', 'relative']);
  });

  it('sorts GPS CSV rows by earliest timestamp', () => {
    const points = parseGpsReplayCsv(`time_stamp,lat,lon,alt,alt_mode
2026-05-11T16:52:17.302053,24.3,121.3,40,amsl
2026-05-11T16:52:16.306518,24.1,121.1,20,relative
2026-05-11T16:52:16.803713,24.2,121.2,30,amsl
`);

    assert.deepEqual(points.map((point) => point.lat), [24.1, 24.2, 24.3]);
    assert.deepEqual(points.map((point) => point.alt), [20, 30, 40]);
    assert.deepEqual(points.map((point) => point.altMode), ['relative', 'amsl', 'amsl']);
  });

  it('keeps replay timing at 2 points per second for 1x', () => {
    assert.equal(GPS_REPLAY_BASE_POINTS_PER_SECOND, 2);
    assert.equal(getGpsReplayIntervalMs(1), 500);
    assert.equal(getGpsReplayIntervalMs(2), 250);
    assert.equal(getGpsReplayIntervalMs(5), 100);
  });
});
