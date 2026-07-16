import type { DevicePayload } from './devicePayload.ts';

interface BuildIssUnetSimRequestBodyParams {
  scene: string;
  sparseRatioPercent: number;
  pixelSizeM: number;
  cfarEnabled: boolean;
  applyBuildingMask: boolean;
  devices: DevicePayload[];
}

interface BuildIssUnetUploadFormDataParams {
  scene: string;
  mode: 'gps' | 'gps_n';
  sparseRatioPercent: number;
  pixelSizeM: number;
  cfarEnabled: boolean;
  applyBuildingMask: boolean;
  filterNoise: boolean;
  gpsFile: File | null;
  noiseFile: File | null;
  devices: DevicePayload[];
}

interface BuildIssUnetStatisticsFormDataParams {
  scene: string;
  pixelSizeM: number;
  applyBuildingMask: boolean;
  filterNoise: boolean;
  gpsFile: File | null;
  noiseFile: File | null;
  devices: DevicePayload[];
}

export function buildIssUnetSimRequestBody({
  scene,
  sparseRatioPercent,
  pixelSizeM,
  cfarEnabled,
  applyBuildingMask,
  devices,
}: BuildIssUnetSimRequestBodyParams) {
  return {
    scene,
    sparse_ratio: sparseRatioPercent / 100,
    pixel_size_m: pixelSizeM,
    cfar: {
      enabled: cfarEnabled,
    },
    apply_building_mask: applyBuildingMask,
    devices,
  };
}

export function buildIssUnetUploadFormData({
  scene,
  mode,
  sparseRatioPercent,
  pixelSizeM,
  cfarEnabled,
  applyBuildingMask,
  filterNoise,
  gpsFile,
  noiseFile,
  devices,
}: BuildIssUnetUploadFormDataParams) {
  const form = new FormData();
  form.append('scene', scene);
  form.append('mode', mode);
  form.append('sparse_ratio', String(sparseRatioPercent / 100));
  form.append('pixel_size_m', String(pixelSizeM));
  form.append('seed', '41');
  form.append('cfar_enabled', String(cfarEnabled));
  form.append('apply_building_mask', String(applyBuildingMask));
  form.append('filter_noise', String(filterNoise));
  form.append('devices_json', JSON.stringify(devices));
  if (gpsFile) {
    form.append('gps_file', gpsFile);
  }
  if (mode === 'gps_n' && noiseFile) {
    form.append('noise_file', noiseFile);
  }
  return form;
}

export function buildIssUnetStatisticsFormData({
  scene,
  pixelSizeM,
  applyBuildingMask,
  filterNoise,
  gpsFile,
  noiseFile,
  devices,
}: BuildIssUnetStatisticsFormDataParams) {
  const form = new FormData();
  form.append('scene', scene);
  form.append('pixel_size_m', String(pixelSizeM));
  form.append('apply_building_mask', String(applyBuildingMask));
  form.append('filter_noise', String(filterNoise));
  form.append('devices_json', JSON.stringify(devices));
  if (gpsFile) {
    form.append('gps_file', gpsFile);
  }
  if (noiseFile) {
    form.append('noise_file', noiseFile);
  }
  return form;
}
