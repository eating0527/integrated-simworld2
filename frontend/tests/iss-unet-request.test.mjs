import assert from 'node:assert/strict';

import { getCurrentDevicePayload } from '../src/utils/devicePayload.ts';
import { buildIssUnetSimRequestBody } from '../src/utils/issUnetRequest.ts';
import { buildIssUnetUploadFormData } from '../src/utils/issUnetRequest.ts';

const body = buildIssUnetSimRequestBody({
  scene: 'NTPU',
  sparseRatioPercent: 20,
  cfarEnabled: true,
  applyBuildingMask: true,
  focusSamplingPoints: true,
  devices: getCurrentDevicePayload(),
});

assert.equal(body.scene, 'NTPU');
assert.equal(body.sparse_ratio, 0.2);
assert.ok(Array.isArray(body.devices));
assert.ok(body.devices.length > 0);
assert.equal(body.devices.some((device) => device.role === 'jammer'), true);

const form = buildIssUnetUploadFormData({
  scene: 'NTPU',
  mode: 'gps_n',
  sparseRatioPercent: 20,
  cfarEnabled: true,
  applyBuildingMask: true,
  focusSamplingPoints: false,
  gpsFile: null,
  noiseFile: null,
  devices: getCurrentDevicePayload(),
});

assert.equal(form.get('scene'), 'NTPU');
assert.equal(form.get('mode'), 'gps_n');
assert.equal(form.get('focus_sampling_points'), 'false');
assert.equal(typeof form.get('devices_json'), 'string');
assert.equal(JSON.parse(form.get('devices_json')).some((device) => device.role === 'jammer'), true);
