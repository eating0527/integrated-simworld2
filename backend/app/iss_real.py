import csv
import io
import json
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, TextIO

import numpy as np

from app.iss_unet_service import BUILDING_MAX_M, ISS_MAX_DBM, ISS_MIN_DBM, SceneDataset


BASE_DIR = Path(__file__).parent
SAMPLE_DIR = BASE_DIR / "sample"
SAMPLE_GPS_PATH = SAMPLE_DIR / "gps.csv"
SAMPLE_NOISE_PATH = SAMPLE_DIR / "noise.csv"

FALLBACK_CENTERS = {
    "NTPU": (24.943476, 121.370054),
    "NYCU": (24.967052, 121.536335),
}


@dataclass(frozen=True)
class GPSPoint:
    time_stamp: datetime
    lat: float
    lon: float
    alt: float
    raw_columns: set[str] = field(default_factory=set)


@dataclass(frozen=True)
class NoisePoint:
    time_stamp: datetime
    noise_floor_db: float
    raw_columns: set[str] = field(default_factory=set)


@dataclass(frozen=True)
class AlignedNoisePoint:
    time_stamp: datetime
    lat: float
    lon: float
    alt: float
    noise_floor_db: float


@dataclass(frozen=True)
class RouteSparseResult:
    sparse_mask: np.ndarray
    outdoor_mask: np.ndarray
    iss_sparse_dbm: np.ndarray
    inputs: np.ndarray
    metrics: dict[str, Any]
    route_points: list[dict[str, Any]] = field(default_factory=list)
    aligned_points: list[dict[str, Any]] = field(default_factory=list)
    sparse_points: list[dict[str, Any]] = field(default_factory=list)


def _open_text(source: Path | str | bytes | TextIO):
    if isinstance(source, Path):
        return source.open("r", encoding="utf-8-sig", newline="")
    if isinstance(source, str) and not ("\n" in source or "," in source):
        path = Path(source)
        if path.exists():
            return path.open("r", encoding="utf-8-sig", newline="")
    if isinstance(source, bytes):
        return io.StringIO(source.decode("utf-8-sig"))
    if isinstance(source, str):
        return io.StringIO(source)
    return source


def _parse_time(value: str) -> datetime:
    text = value.strip()
    if not text:
        raise ValueError("time_stamp is required")
    try:
        numeric = float(text)
        return datetime.fromtimestamp(numeric, tz=timezone.utc)
    except ValueError:
        pass
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _read_rows(source: Path | str | bytes | TextIO) -> tuple[list[dict[str, str]], set[str]]:
    handle = _open_text(source)
    should_close = handle is not source
    try:
        reader = csv.DictReader(handle)
        columns = set(reader.fieldnames or [])
        return list(reader), columns
    finally:
        if should_close:
            handle.close()


def _require_columns(columns: set[str], required: Iterable[str], source_name: str) -> None:
    missing = set(required) - columns
    if missing:
        raise ValueError(f"{source_name} missing required columns: {', '.join(sorted(missing))}")


def parse_gps_csv(source: Path | str | bytes | TextIO) -> list[GPSPoint]:
    rows, columns = _read_rows(source)
    _require_columns(columns, ("time_stamp", "lat", "lon", "alt"), "GPS CSV")
    points = [
        GPSPoint(
            time_stamp=_parse_time(row["time_stamp"]),
            lat=float(row["lat"]),
            lon=float(row["lon"]),
            alt=float(row["alt"]),
            raw_columns=columns,
        )
        for row in rows
        if row.get("time_stamp")
    ]
    points.sort(key=lambda point: point.time_stamp)
    return points


def parse_noise_csv(source: Path | str | bytes | TextIO) -> list[NoisePoint]:
    rows, columns = _read_rows(source)
    _require_columns(columns, ("time_stamp", "noise_floor_db"), "Noise CSV")
    points = [
        NoisePoint(
            time_stamp=_parse_time(row["time_stamp"]),
            noise_floor_db=float(row["noise_floor_db"]),
            raw_columns=columns,
        )
        for row in rows
        if row.get("time_stamp")
    ]
    points.sort(key=lambda point: point.time_stamp)
    return points


def align_noise_to_gps(
    gps_points: list[GPSPoint],
    noise_points: list[NoisePoint],
) -> tuple[list[AlignedNoisePoint], int]:
    aligned: list[AlignedNoisePoint] = []
    skipped = 0
    gps_index = 0
    gps_sorted = sorted(gps_points, key=lambda point: point.time_stamp)
    for noise in sorted(noise_points, key=lambda point: point.time_stamp):
        while gps_index + 1 < len(gps_sorted) and gps_sorted[gps_index + 1].time_stamp <= noise.time_stamp:
            gps_index += 1
        if not gps_sorted or gps_sorted[gps_index].time_stamp > noise.time_stamp:
            skipped += 1
            continue
        delta = (noise.time_stamp - gps_sorted[gps_index].time_stamp).total_seconds()
        if delta >= 1.0:
            skipped += 1
            continue
        gps = gps_sorted[gps_index]
        aligned.append(
            AlignedNoisePoint(
                time_stamp=noise.time_stamp,
                lat=gps.lat,
                lon=gps.lon,
                alt=gps.alt,
                noise_floor_db=noise.noise_floor_db,
            )
        )
    return aligned, skipped


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def resolve_scene_center(dataset: SceneDataset) -> tuple[float, float] | None:
    if dataset.meta_path:
        meta = _read_json(dataset.meta_path)
        if meta.get("center_lat") is not None and meta.get("center_lon") is not None:
            return float(meta["center_lat"]), float(meta["center_lon"])
    sibling_meta = dataset.data_dir.parent / "scene_metadata.json"
    if sibling_meta.exists():
        meta = _read_json(sibling_meta)
        if meta.get("lat") is not None and meta.get("lon") is not None:
            return float(meta["lat"]), float(meta["lon"])
    return FALLBACK_CENTERS.get(dataset.scene)


def _scene_area_m(dataset: SceneDataset) -> float:
    if dataset.meta_path:
        meta = _read_json(dataset.meta_path)
        if meta.get("area_m") is not None:
            return float(meta["area_m"])
    return 512.0


def _scene_grid_bounds(dataset: SceneDataset, shape: tuple[int, int]) -> dict[str, float] | None:
    if not dataset.meta_path:
        return None
    rows, cols = shape
    raw_bounds = _read_json(dataset.meta_path).get("grid_bounds")
    if not isinstance(raw_bounds, dict):
        return None
    try:
        min_x = float(raw_bounds["min_x"])
        max_x = float(raw_bounds["max_x"])
        min_y = float(raw_bounds["min_y"])
        max_y = float(raw_bounds["max_y"])
    except (KeyError, TypeError, ValueError):
        return None
    if not all(math.isfinite(value) for value in (min_x, max_x, min_y, max_y)) or max_x <= min_x or max_y <= min_y:
        return None
    return {
        "min_x": min_x,
        "max_y": max_y,
        "pixel_size_x_m": float((max_x - min_x) / float(cols)),
        "pixel_size_y_m": float((max_y - min_y) / float(rows)),
    }


def _latlon_to_pixel(
    lat: float,
    lon: float,
    center_lat: float,
    center_lon: float,
    area_m: float,
    shape: tuple[int, int],
) -> tuple[int, int] | None:
    rows, cols = shape
    meters_per_deg_lat = 111320.0
    meters_per_deg_lon = max(1.0, meters_per_deg_lat * math.cos(math.radians(center_lat)))
    east_m = (lon - center_lon) * meters_per_deg_lon
    north_m = (lat - center_lat) * meters_per_deg_lat
    pixel_x_m = area_m / cols
    pixel_y_m = area_m / rows
    col = int(math.floor((east_m + area_m / 2.0) / pixel_x_m))
    row = int(math.floor((area_m / 2.0 - north_m) / pixel_y_m))
    if 0 <= row < rows and 0 <= col < cols:
        return row, col
    return None


def _pixel_to_world(
    row: int,
    col: int,
    area_m: float,
    shape: tuple[int, int],
    grid_bounds: dict[str, float] | None = None,
) -> tuple[float, float]:
    if grid_bounds is not None:
        world_x = grid_bounds["min_x"] + (float(col) + 0.5) * grid_bounds["pixel_size_x_m"]
        north_m = grid_bounds["max_y"] - (float(row) + 0.5) * grid_bounds["pixel_size_y_m"]
        return float(world_x), float(-north_m)
    rows, cols = shape
    pixel_x_m = area_m / cols
    pixel_y_m = area_m / rows
    world_x = -area_m / 2.0 + (float(col) + 0.5) * pixel_x_m
    north_m = area_m / 2.0 - (float(row) + 0.5) * pixel_y_m
    return float(world_x), float(-north_m)


def _route_point_payload(
    point: GPSPoint | AlignedNoisePoint,
    row: int,
    col: int,
    area_m: float,
    shape: tuple[int, int],
    grid_bounds: dict[str, float] | None = None,
) -> dict[str, Any]:
    world_x, world_z = _pixel_to_world(row, col, area_m, shape, grid_bounds)
    payload: dict[str, Any] = {
        "time_stamp": point.time_stamp.isoformat(),
        "lat": float(point.lat),
        "lon": float(point.lon),
        "alt": float(point.alt),
        "row": int(row),
        "col": int(col),
        "world_x": world_x,
        "world_z": world_z,
        "in_bounds": True,
    }
    if isinstance(point, AlignedNoisePoint):
        payload["noise_floor_db"] = float(point.noise_floor_db)
        payload["used_in_sparse"] = False
    return payload


def _normalize_radio_map(values: np.ndarray) -> np.ndarray:
    return np.clip((values - ISS_MIN_DBM) / (ISS_MAX_DBM - ISS_MIN_DBM), 0.0, 1.0)


def _route_points_for_mode(
    mode: str,
    gps_points: list[GPSPoint],
    noise_points: list[NoisePoint] | None,
) -> tuple[list[GPSPoint | AlignedNoisePoint], int, int]:
    if mode == "gps":
        return list(gps_points), 0, 0
    if mode == "gps_n":
        aligned, skipped = align_noise_to_gps(gps_points, noise_points or [])
        return aligned, len(aligned), skipped
    raise ValueError("mode must be 'gps' or 'gps_n'")


def create_route_sparse_sample(
    arrays: dict[str, np.ndarray],
    dataset: SceneDataset,
    mode: str,
    gps_points: list[GPSPoint] | None = None,
    noise_points: list[NoisePoint] | None = None,
    apply_building_mask: bool = True,
) -> RouteSparseResult:
    sample_used = gps_points is None or (mode == "gps_n" and noise_points is None)
    if gps_points is None:
        gps_points = parse_gps_csv(SAMPLE_GPS_PATH)
    if mode == "gps_n" and noise_points is None:
        noise_points = parse_noise_csv(SAMPLE_NOISE_PATH)

    center = resolve_scene_center(dataset)
    if center is None:
        raise ValueError("scene center is required for GPS ISS_UNET mode")

    building = arrays["building"]
    sparse_mask = np.zeros_like(building, dtype=np.float32)
    outdoor_mask = (building <= 3.0).astype(np.float32)
    iss_sparse_dbm = np.full_like(building, ISS_MIN_DBM, dtype=np.float32)
    area_m = _scene_area_m(dataset)
    grid_bounds = _scene_grid_bounds(dataset, building.shape)
    route_points, aligned_noise, skipped_noise = _route_points_for_mode(mode, gps_points, noise_points)
    out_of_bounds = 0
    indoor_filtered = 0
    valid_projected_points = 0
    duplicate_points = 0
    valid_projected_noise_dbm: list[float] = []
    projected_route_points: list[dict[str, Any]] = []
    projected_aligned_points: list[dict[str, Any]] = []
    projected_sparse_points: list[dict[str, Any]] = []

    for gps_point in gps_points:
        pixel = _latlon_to_pixel(gps_point.lat, gps_point.lon, center[0], center[1], area_m, building.shape)
        if pixel is not None:
            row, col = pixel
            projected_route_points.append(_route_point_payload(gps_point, row, col, area_m, building.shape, grid_bounds))

    for point in route_points:
        pixel = _latlon_to_pixel(point.lat, point.lon, center[0], center[1], area_m, building.shape)
        if pixel is None:
            out_of_bounds += 1
            continue
        row, col = pixel
        payload = _route_point_payload(point, row, col, area_m, building.shape, grid_bounds)
        if isinstance(point, AlignedNoisePoint):
            projected_aligned_points.append(payload)
        if apply_building_mask and outdoor_mask[row, col] < 0.5:
            indoor_filtered += 1
            continue
        if sparse_mask[row, col] > 0.5:
            duplicate_points += 1
        else:
            sparse_mask[row, col] = 1.0
        valid_projected_points += 1
        if isinstance(point, AlignedNoisePoint):
            clipped_noise = float(np.clip(point.noise_floor_db, ISS_MIN_DBM, ISS_MAX_DBM))
            iss_sparse_dbm[row, col] = clipped_noise
            valid_projected_noise_dbm.append(clipped_noise)
            payload["used_in_sparse"] = True
            projected_sparse_points.append(dict(payload))
        else:
            iss_sparse_dbm[row, col] = float(arrays["iss"][row, col])

    building_norm = np.clip(building / BUILDING_MAX_M, 0.0, 1.0)
    dss_norm = _normalize_radio_map(arrays["dss"])
    inputs = np.stack(
        [
            building_norm,
            _normalize_radio_map(iss_sparse_dbm) * sparse_mask,
            sparse_mask,
            outdoor_mask,
            dss_norm,
        ],
        axis=0,
    ).astype(np.float32)
    metrics = {
        "mode": mode,
        "route_points": len(gps_points),
        "used_samples": int(sparse_mask.sum()),
        "aligned_noise": aligned_noise,
        "skipped_noise": skipped_noise,
        "sample_used": sample_used,
        "apply_building_mask": apply_building_mask,
        "out_of_bounds": out_of_bounds,
        "indoor_filtered": indoor_filtered,
        "valid_projected_points": valid_projected_points,
        "duplicate_points": duplicate_points,
        "valid_projected_noise_dbm": valid_projected_noise_dbm,
    }
    return RouteSparseResult(
        sparse_mask=sparse_mask,
        outdoor_mask=outdoor_mask,
        iss_sparse_dbm=iss_sparse_dbm,
        inputs=inputs,
        metrics=metrics,
        route_points=projected_route_points,
        aligned_points=projected_aligned_points,
        sparse_points=projected_sparse_points,
    )
