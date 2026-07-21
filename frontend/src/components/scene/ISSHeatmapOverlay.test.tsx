import { describe, expect, it } from 'vitest';
import { validateHeatmapOverlayPayload } from './ISSHeatmapOverlay';

const valid = (overrides: Record<string, unknown> = {}) => ({
  success: true,
  rows: 2,
  cols: 2,
  area_m: 512,
  min_dbm: -90,
  max_dbm: -15,
  values: [[-80, -40], [-60, -20]],
  ...overrides,
});

describe('validateHeatmapOverlayPayload', () => {
  it('accepts an exact finite grid', () => {
    expect(validateHeatmapOverlayPayload(valid(), { rows: 2, cols: 2 })).toMatchObject({ kind: 'ready' });
  });

  it.each([
    ['non-integer rows', { rows: 1.5 }],
    ['oversized rows', { rows: 513 }],
    ['oversized cells', { rows: 512, cols: 513 }],
    ['shape mismatch', { values: [[-1]] }],
    ['nonfinite cell', { values: [[-1, NaN], [-1, -1]] }],
    ['unordered range', { min_dbm: 1, max_dbm: 0 }],
    ['nonfinite metadata', { max_dbm: Infinity }],
  ])('rejects %s', (_label, overrides) => {
    expect(() => validateHeatmapOverlayPayload(valid(overrides))).toThrow();
  });

  it('preserves explicit empty semantics', () => {
    expect(validateHeatmapOverlayPayload({ success: false })).toEqual({ kind: 'empty' });
    expect(validateHeatmapOverlayPayload({ empty: true })).toEqual({ kind: 'empty' });
  });
});
