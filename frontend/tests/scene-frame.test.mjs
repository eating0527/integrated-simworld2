import assert from 'node:assert/strict';
import { describe, it } from 'vitest';

import { createSceneFrame, parseSceneFrame } from '../src/types/sceneFrame.ts';

describe('SceneFrame validation', () => {
  it('accepts the fixed 512m ENU frame', () => {
    const frame = createSceneFrame('scene-test', { lat: 24, lon: 121, alt_m: 0 });
    assert.equal(parseSceneFrame(frame)?.frame_id, 'scene-test');
  });

  it('rejects legacy or non-fixed frame metadata', () => {
    const frame = createSceneFrame('scene-test', { lat: 24, lon: 121, alt_m: 0 });
    assert.equal(parseSceneFrame({ ...frame, extent: { ...frame.extent, max_e: 512 } }), null);
    assert.equal(parseSceneFrame({ center_lat: 24, center_lon: 121, area_m: 512 }), null);
  });
});
