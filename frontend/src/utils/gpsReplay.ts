export const GPS_REPLAY_BASE_POINTS_PER_SECOND = 2;

export type GpsReplayRate = 1 | 2 | 5;

export interface GpsReplayPoint {
  timeMs: number;
  timeStamp: string;
  lat: number;
  lon: number;
  alt: number;
}

export function getGpsReplayIntervalMs(rate: GpsReplayRate) {
  return 1000 / (GPS_REPLAY_BASE_POINTS_PER_SECOND * rate);
}

export function parseGpsReplayCsv(text: string): GpsReplayPoint[] {
  const lines = text
    .replace(/^\uFEFF/, '')
    .split(/\r?\n/)
    .map(line => line.trim())
    .filter(Boolean);
  if (lines.length < 2) return [];

  const headers = splitCsvLine(lines[0]).map(header => header.trim());
  const timeIndex = headers.indexOf('time_stamp');
  const latIndex = headers.indexOf('lat');
  const lonIndex = headers.indexOf('lon');
  const altIndex = headers.indexOf('alt');
  if (timeIndex < 0 || latIndex < 0 || lonIndex < 0) return [];

  return lines
    .slice(1)
    .map(line => {
      const cells = splitCsvLine(line);
      const timeStamp = cells[timeIndex]?.trim() ?? '';
      const timeMs = parseTimeMs(timeStamp);
      const lat = Number(cells[latIndex]);
      const lon = Number(cells[lonIndex]);
      const alt = altIndex >= 0 ? Number(cells[altIndex]) : 0;
      if (!Number.isFinite(timeMs) || !Number.isFinite(lat) || !Number.isFinite(lon)) {
        return null;
      }
      return {
        timeMs,
        timeStamp,
        lat,
        lon,
        alt: Number.isFinite(alt) ? alt : 0,
      };
    })
    .filter((point): point is GpsReplayPoint => point !== null)
    .sort((a, b) => a.timeMs - b.timeMs);
}

function parseTimeMs(value: string) {
  const numeric = Number(value);
  if (Number.isFinite(numeric)) {
    return numeric > 1e12 ? numeric : numeric * 1000;
  }
  return Date.parse(value.endsWith('Z') ? value : `${value}Z`);
}

function splitCsvLine(line: string) {
  const cells: string[] = [];
  let cell = '';
  let quoted = false;
  for (let index = 0; index < line.length; index += 1) {
    const char = line[index];
    const next = line[index + 1];
    if (char === '"' && quoted && next === '"') {
      cell += '"';
      index += 1;
    } else if (char === '"') {
      quoted = !quoted;
    } else if (char === ',' && !quoted) {
      cells.push(cell);
      cell = '';
    } else {
      cell += char;
    }
  }
  cells.push(cell);
  return cells;
}
