import { afterEach, describe, expect, it, vi } from 'vitest';
import { render, waitFor } from '@testing-library/react';
import { createSceneFrame } from '../../types/sceneFrame';
import type { HeatmapOverlayConfig } from '../../types/heatmap';
import { ISSHeatmapOverlay, validateHeatmapOverlayPayload } from './ISSHeatmapOverlay';

const mocks = vi.hoisted(() => ({ dispose: vi.fn() }));
vi.mock('three', async (importOriginal) => {
  const actual = await importOriginal<typeof import('three')>();
  class MockCanvasTexture {
    dispose = mocks.dispose;
    needsUpdate = false;
  }
  return { ...actual, CanvasTexture: MockCanvasTexture };
});

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

const overlay: HeatmapOverlayConfig = {
  url: '/api/grid',
  rows: 2,
  cols: 2,
  areaM: 512,
  frame_id: 'scene-test',
  frame: createSceneFrame('scene-test', { lat: 24, lon: 121, alt_m: 0 }),
  grid: { rows: 2, cols: 2, pixel_size_e_m: 256, pixel_size_n_m: 256 },
  opacity: 0.7,
  vminDbm: -90,
  vmaxDbm: -15,
};

function response(body: unknown, ok = true) {
  return { ok, status: ok ? 200 : 500, json: vi.fn().mockResolvedValue(body) } as unknown as Response;
}

afterEach(() => {
  vi.restoreAllMocks();
  mocks.dispose.mockClear();
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
    ['zero-width range', { min_dbm: -15, max_dbm: -15 }],
    ['nonfinite metadata', { max_dbm: Infinity }],
  ])('rejects %s', (_label, overrides) => {
    expect(() => validateHeatmapOverlayPayload(valid(overrides))).toThrow();
  });

  it('preserves explicit empty semantics', () => {
    expect(validateHeatmapOverlayPayload({ success: false })).toEqual({ kind: 'empty' });
    expect(validateHeatmapOverlayPayload({ empty: true })).toEqual({ kind: 'empty' });
  });
});

describe('ISSHeatmapOverlay request lifecycle', () => {
  it.each([
    ['empty', response({ success: false }), 'empty'],
    ['HTTP failure', response({}, false), 'error'],
    ['invalid JSON payload', response({ rows: 2 }), 'error'],
  ])('reports %s without allocating a texture', async (_label, fetchResponse, expected) => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(fetchResponse);
    const onStatusChange = vi.fn();

    render(<ISSHeatmapOverlay overlay={overlay} onStatusChange={onStatusChange} />);

    await waitFor(() => expect(onStatusChange).toHaveBeenLastCalledWith(expected));
    expect(mocks.dispose).not.toHaveBeenCalled();
  });

  it('aborts the stale request when retrying', async () => {
    const signals: AbortSignal[] = [];
    vi.spyOn(globalThis, 'fetch').mockImplementation((_url, init) => {
      signals.push(init!.signal!);
      return new Promise<Response>(() => {});
    });
    const onStatusChange = vi.fn();
    const view = render(<ISSHeatmapOverlay overlay={overlay} retryKey={0} onStatusChange={onStatusChange} />);

    await waitFor(() => expect(signals).toHaveLength(1));
    view.rerender(<ISSHeatmapOverlay overlay={overlay} retryKey={1} onStatusChange={onStatusChange} />);

    await waitFor(() => expect(signals).toHaveLength(2));
    expect(signals[0].aborted).toBe(true);
    expect(signals[1].aborted).toBe(false);
  });

  it('creates and disposes a validated texture', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(response(valid()));
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({
      createImageData: (width: number, height: number) => ({ data: new Uint8ClampedArray(width * height * 4) }),
      putImageData: vi.fn(),
    } as unknown as CanvasRenderingContext2D);
    const onStatusChange = vi.fn();
    const view = render(<ISSHeatmapOverlay overlay={overlay} onStatusChange={onStatusChange} />);

    await waitFor(() => expect(onStatusChange).toHaveBeenLastCalledWith('ready'));
    view.unmount();

    expect(mocks.dispose).toHaveBeenCalledTimes(1);
  });
});
