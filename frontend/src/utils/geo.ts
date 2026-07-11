/**
 * GPS (WGS84) → ENU 座標轉換
 *
 * @param lat     目標緯度
 * @param lon     目標經度
 * @param alt     目標高度 (m)
 * @param origin  原點 { lat, lon, alt }
 * @param rotation 地圖旋轉角度 (度，逆時針為正)
 * @returns [x (東向), y (南→北，已翻轉), z (上向)]
 */
export function latLonToENU(
  lat: number,
  lon: number,
  alt: number,
  origin: { lat: number; lon: number; alt: number },
  rotation = 0
): [number, number, number] {
  const R = 6_378_137; // 地球半徑 (m)
  const dLat = (lat - origin.lat) * (Math.PI / 180);
  const dLon = (lon - origin.lon) * (Math.PI / 180);

  let x = dLon * R * Math.cos(origin.lat * (Math.PI / 180)); // 東向
  let y = -dLat * R;                                          // 南北（已翻轉使 y 朝北增大）
  const z = (alt ?? 0) - origin.alt;                          // 上向

  if (rotation !== 0) {
    const rad = rotation * (Math.PI / 180);
    const xr = x * Math.cos(rad) - y * Math.sin(rad);
    const yr = x * Math.sin(rad) + y * Math.cos(rad);
    x = xr;
    y = yr;
  }

  return [x, y, z];
}

export function worldXZToLatLon(
  x: number,
  z: number,
  origin: { lat: number; lon: number; alt: number },
): { lat: number; lon: number; alt: number } {
  const R = 6_378_137;
  const dLat = -z / R;
  const dLon = x / (R * Math.cos(origin.lat * (Math.PI / 180)));

  return {
    lat: origin.lat + dLat * (180 / Math.PI),
    lon: origin.lon + dLon * (180 / Math.PI),
    alt: origin.alt,
  };
}
