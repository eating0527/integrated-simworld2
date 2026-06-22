async (page) => {
  await page.waitForLoadState('networkidle', { timeout: 30000 }).catch(() => {});
  const results = await page.evaluate(async () => {
    const devices = [
      { name: 'tx-0', role: 'tx', x: -75, y: 0, z: 75, power_dbm: 60 },
      { name: 'rx-0', role: 'rx', x: -30, y: 10, z: 175, power_dbm: null },
      { name: 'jam-0', role: 'jammer', x: -150, y: 0, z: 170, power_dbm: 20 },
    ];
    const scenes = [
      { label: 'ntpu', scene: 'ntpu' },
      { label: 'bench', scene: 'T-A609F0BDA6' },
    ];
    const modes = ['sim', 'gps_n'];
    const pixels = [1, 2, 4];
    const out = [];

    async function loadImage(url) {
      return await new Promise((resolve) => {
        const img = new Image();
        img.onload = () => resolve({ loaded: true, width: img.naturalWidth, height: img.naturalHeight });
        img.onerror = () => resolve({ loaded: false, width: 0, height: 0 });
        img.src = `${url}${url.includes('?') ? '&' : '?'}pw=${Date.now()}${Math.random()}`;
      });
    }

    for (const s of scenes) {
      for (const mode of modes) {
        for (const px of pixels) {
          if (mode === 'sim') {
            const body = {
              scene: s.scene,
              sparse_ratio: 0.2,
              pixel_size_m: px,
              cfar: { enabled: true },
              apply_building_mask: true,
              focus_sampling_points: true,
              devices,
            };
            const res = await fetch('/api/iss-unet/reconstruct', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify(body),
            });
            const json = await res.json().catch(() => ({}));
            const imgUrl = json.images?.comparison || json.images?.reconstructed || json.images?.cfar || null;
            const loaded = imgUrl ? await loadImage(imgUrl) : { loaded: false, width: 0, height: 0 };
            out.push({
              scene: s.label,
              scene_id: s.scene,
              mode,
              pixel_size_m: px,
              request_power_dbm: 20,
              status: res.status,
              ok: res.ok,
              grid_res: json.metrics?.grid_res,
              output_shape: json.metrics?.output_shape,
              image: imgUrl,
              image_loaded: loaded.loaded,
              image_width: loaded.width,
              image_height: loaded.height,
              error: json.error || json.detail || null,
            });
          } else {
            const form = new FormData();
            form.append('scene', s.scene);
            form.append('mode', 'gps_n');
            form.append('sparse_ratio', '0.2');
            form.append('pixel_size_m', String(px));
            form.append('seed', '41');
            form.append('cfar_enabled', 'true');
            form.append('apply_building_mask', 'true');
            form.append('focus_sampling_points', 'true');
            form.append('devices_json', JSON.stringify(devices));
            const res = await fetch('/api/iss-unet/reconstruct/upload', { method: 'POST', body: form });
            const json = await res.json().catch(() => ({}));
            const imgUrl = json.images?.comparison || json.images?.reconstructed || json.images?.cfar || null;
            const loaded = imgUrl ? await loadImage(imgUrl) : { loaded: false, width: 0, height: 0 };
            out.push({
              scene: s.label,
              scene_id: s.scene,
              mode,
              pixel_size_m: px,
              request_power_dbm: 20,
              status: res.status,
              ok: res.ok,
              grid_res: json.metrics?.grid_res,
              output_shape: json.metrics?.output_shape,
              used_samples: json.metrics?.used_samples,
              sample_used: json.metrics?.sample_used,
              image: imgUrl,
              image_loaded: loaded.loaded,
              image_width: loaded.width,
              image_height: loaded.height,
              error: json.error || json.detail || null,
            });
          }
        }
      }
    }

    window.__issUnetMatrixResults = out;
    const existing = document.getElementById('iss-unet-matrix-results');
    if (existing) {
      existing.remove();
    }
    const pre = document.createElement('pre');
    pre.id = 'iss-unet-matrix-results';
    pre.textContent = JSON.stringify(out, null, 2);
    pre.style.position = 'fixed';
    pre.style.left = '8px';
    pre.style.top = '8px';
    pre.style.zIndex = '99999';
    pre.style.maxWidth = '720px';
    pre.style.maxHeight = '80vh';
    pre.style.overflow = 'auto';
    pre.style.background = 'rgba(0,0,0,.88)';
    pre.style.color = '#0f0';
    pre.style.fontSize = '11px';
    pre.style.padding = '8px';
    document.body.appendChild(pre);
    return out;
  });
  console.log(JSON.stringify(results, null, 2));
}
