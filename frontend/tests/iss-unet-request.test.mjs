import assert from 'node:assert/strict';
import { describe, it } from 'vitest';

import { getCurrentDevicePayload } from '../src/utils/devicePayload.ts';
import {
  buildIssUnetSimRequestBody,
  buildIssUnetStatisticsFormData,
  buildIssUnetUploadFormData,
} from '../src/utils/issUnetRequest.ts';

describe('ISS_UNET request builders', () => {
  it('builds sim JSON request bodies', () => {
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
  });

  it('builds upload FormData request bodies', () => {
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
  });

  it('builds gps_n statistics FormData without hard-coded sample files', () => {
    const form = buildIssUnetStatisticsFormData({
      scene: 'NTPU',
      applyBuildingMask: true,
      focusSamplingPoints: true,
      gpsFile: null,
      noiseFile: null,
      devices: getCurrentDevicePayload(),
    });

    assert.equal(form.get('scene'), 'NTPU');
    assert.equal(form.get('apply_building_mask'), 'true');
    assert.equal(form.get('focus_sampling_points'), 'true');
    assert.equal(form.get('gps_file'), null);
    assert.equal(form.get('noise_file'), null);
    assert.equal(typeof form.get('devices_json'), 'string');
    assert.equal(JSON.parse(form.get('devices_json')).some((device) => device.role === 'jammer'), true);
  });
});
