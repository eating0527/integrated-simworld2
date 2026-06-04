import type { DevicePayload } from './devicePayload.ts';

interface BuildIssUnetSimRequestBodyParams {
  scene: string;
  sparseRatioPercent: number;
  cfarEnabled: boolean;
  applyBuildingMask: boolean;
  focusSamplingPoints: boolean;
  devices: DevicePayload[];
}

interface BuildIssUnetUploadFormDataParams {
  scene: string;
  mode: 'gps' | 'gps_n';
  sparseRatioPercent: number;
  cfarEnabled: boolean;
  applyBuildingMask: boolean;
  focusSamplingPoints: boolean;
  gpsFile: File | null;
  noiseFile: File | null;
  devices: DevicePayload[];
}

export function buildIssUnetSimRequestBody({
  scene,
  sparseRatioPercent,
  cfarEnabled,
  applyBuildingMask,
  focusSamplingPoints,
  devices,
}: BuildIssUnetSimRequestBodyParams) {
  return {
    scene,
    sparse_ratio: sparseRatioPercent / 100,
    cfar: {
      enabled: cfarEnabled,
    },
    apply_building_mask: applyBuildingMask,
    focus_sampling_points: focusSamplingPoints,
    devices,
  };
}

export function buildIssUnetUploadFormData({
  scene,
  mode,
  sparseRatioPercent,
  cfarEnabled,
  applyBuildingMask,
  focusSamplingPoints,
  gpsFile,
  noiseFile,
  devices,
}: BuildIssUnetUploadFormDataParams) {
  const form = new FormData();
  form.append('scene', scene);
  form.append('mode', mode);
  form.append('sparse_ratio', String(sparseRatioPercent / 100));
  form.append('seed', '41');
  form.append('cfar_enabled', String(cfarEnabled));
  form.append('apply_building_mask', String(applyBuildingMask));
  form.append('focus_sampling_points', String(focusSamplingPoints));
  form.append('devices_json', JSON.stringify(devices));
  if (gpsFile) {
    form.append('gps_file', gpsFile);
  }
  if (mode === 'gps_n' && noiseFile) {
    form.append('noise_file', noiseFile);
  }
  return form;
}
