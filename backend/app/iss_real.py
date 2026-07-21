import csv
import io
import json
import math
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, TextIO

import numpy as np

from app.coordinate_frame import (
    SceneFrame,
    enu_to_gps,
    enu_to_grid,
    gps_to_enu,
    grid_to_enu,
    scene_frame_from_metadata,
)
from app.iss_unet_service import BUILDING_MAX_M, ISS_MAX_DBM, ISS_MIN_DBM, SceneDataset


BASE_DIR = Path(__file__).parent
SAMPLE_DIR = BASE_DIR / "sample"
SAMPLE_GPS_PATH = SAMPLE_DIR / "gps.csv"
SAMPLE_NOISE_PATH = SAMPLE_DIR / "noise.csv"

@dataclass(frozen=True)
class GPSPoint:
    time_stamp: datetime
    lat: float
    lon: float
    alt: float
    raw_columns: set[str] = field(default_factory=set)
    alt_mode: str = "relative"
    legacy_alt_mode: bool = False


@dataclass(frozen=True)
class NoisePoint:
    time_stamp: datetime | None
    noise_floor_db: float | None
    raw_columns: set[str] = field(default_factory=set)
    filtered: bool = False


@dataclass(frozen=True)
class AlignedNoisePoint:
    time_stamp: datetime
    lat: float
    lon: float
    alt: float
    noise_floor_db: float | None
    alt_mode: str = "relative"
    legacy_alt_mode: bool = False


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
    has_alt_mode = "alt_mode" in columns
    points = [
        GPSPoint(
            time_stamp=_parse_time(row["time_stamp"]),
            lat=float(row["lat"]),
            lon=float(row["lon"]),
            alt=float(row["alt"]),
            raw_columns=columns,
            alt_mode=(row.get("alt_mode") or "relative").strip().lower() if has_alt_mode else "relative",
            legacy_alt_mode=not has_alt_mode,
        )
        for row in rows
        if row.get("time_stamp")
    ]
    points.sort(key=lambda point: point.time_stamp)
    return points


def parse_noise_csv(source: Path | str | bytes | TextIO) -> list[NoisePoint]:
    rows, columns = _read_rows(source)
    _require_columns(columns, ("time_stamp", "noise_floor_db"), "Noise CSV")
    points = []
    for row in rows:
        try:
            time_stamp = _parse_time(row.get("time_stamp", ""))
        except (TypeError, ValueError, OverflowError, OSError):
            time_stamp = None
        try:
            noise_floor_db = float(row.get("noise_floor_db", ""))
            if not math.isfinite(noise_floor_db):
                noise_floor_db = None
        except (TypeError, ValueError):
            noise_floor_db = None
        points.append(NoisePoint(time_stamp, noise_floor_db, columns))
    points.sort(key=lambda point: point.time_stamp or datetime.max.replace(tzinfo=timezone.utc))
    return points


def align_noise_to_gps(
    gps_points: list[GPSPoint],
    noise_points: list[NoisePoint],
) -> tuple[list[AlignedNoisePoint], int]:
    aligned: list[AlignedNoisePoint] = []
    skipped = 0
    gps_index = 0
    gps_sorted = sorted(gps_points, key=lambda point: point.time_stamp)
    for noise in sorted(noise_points, key=lambda point: point.time_stamp or datetime.max.replace(tzinfo=timezone.utc)):
        if noise.time_stamp is None:
            skipped += 1
            continue
        while gps_index + 1 < len(gps_sorted) and gps_sorted[gps_index + 1].time_stamp <= noise.time_stamp:
            gps_index += 1
        if not gps_sorted or gps_sorted[gps_index].time_stamp > noise.time_stamp:
            if not noise.filtered:
                skipped += 1
            continue
        delta = (noise.time_stamp - gps_sorted[gps_index].time_stamp).total_seconds()
        if delta >= 1.0:
            if not noise.filtered:
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
                alt_mode=gps.alt_mode,
                legacy_alt_mode=gps.legacy_alt_mode,
            )
        )
    return aligned, skipped


def _prepare_noise_points(
    noise_points: list[NoisePoint],
    filter_noise: bool,
) -> list[NoisePoint]:
    prepared: list[NoisePoint] = []
    for point in noise_points:
        value = point.noise_floor_db
        invalid = value is None or not math.isfinite(value) or (filter_noise and value >= -1.0)
        if invalid:
            prepared.append(
                replace(
                    point,
                    noise_floor_db=None,
                    filtered=point.time_stamp is not None,
                )
            )
        else:
            prepared.append(point)
    return prepared


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def resolve_scene_frame(dataset: SceneDataset) -> SceneFrame:
    if dataset.meta_path is None:
        raise ValueError(f"SceneFrame metadata is required for {dataset.scene}")
    return scene_frame_from_metadata(_read_json(dataset.meta_path))


def resolve_scene_center(dataset: SceneDataset) -> tuple[float, float]:
    frame = resolve_scene_frame(dataset)
    return frame.origin_lat, frame.origin_lon


def _scene_area_m(dataset: SceneDataset) -> float:
    resolve_scene_frame(dataset)
    return 512.0


def _scene_grid_bounds(dataset: SceneDataset, shape: tuple[int, int]) -> dict[str, float] | None:
    resolve_scene_frame(dataset)
    rows, cols = shape
    return {
        "min_x": -256.0,
        "max_x": 256.0,
        "min_y": -256.0,
        "max_y": 256.0,
        "pixel_size_x_m": 512.0 / float(cols),
        "pixel_size_y_m": 512.0 / float(rows),
    }


def _latlon_to_grid(point: GPSPoint | AlignedNoisePoint, frame: SceneFrame):
    east_m, north_m, up_m = gps_to_enu(point.lat, point.lon, point.alt, frame, point.alt_mode)
    return enu_to_grid(east_m, north_m, up_m, frame), (east_m, north_m, up_m)


def _route_point_payload(
    point: GPSPoint | AlignedNoisePoint,
    frame: SceneFrame,
) -> dict[str, Any]:
    grid, enu = _latlon_to_grid(point, frame)
    lat, lon, alt = enu_to_gps(*enu, frame, point.alt_mode)
    payload: dict[str, Any] = {
        "time_stamp": point.time_stamp.isoformat(),
        "lat": lat,
        "lon": lon,
        "alt": alt,
        "alt_mode": point.alt_mode,
        "legacy_alt_mode": point.legacy_alt_mode,
        "frame_id": frame.frame_id,
        "enu": {"east_m": enu[0], "north_m": enu[1], "up_m": enu[2]},
        "grid": grid.to_dict(),
        "inside_extent": grid.inside_extent,
        "displayable": grid.displayable,
    }
    if isinstance(point, AlignedNoisePoint):
        payload["noise_floor_db"] = None if point.noise_floor_db is None else float(point.noise_floor_db)
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
    filter_noise: bool = True,
) -> RouteSparseResult:
    sample_used = gps_points is None or (mode == "gps_n" and noise_points is None)
    if gps_points is None:
        gps_points = parse_gps_csv(SAMPLE_GPS_PATH)
    if mode == "gps_n" and noise_points is None:
        noise_points = parse_noise_csv(SAMPLE_NOISE_PATH)
    if mode == "gps_n":
        noise_points = _prepare_noise_points(noise_points or [], filter_noise)
    else:
        noise_points = noise_points or []

    frame = resolve_scene_frame(dataset)

    building = arrays["building"]
    sparse_mask = np.zeros_like(building, dtype=np.float32)
    outdoor_mask = (building <= 3.0).astype(np.float32)
    iss_sparse_dbm = np.full_like(building, ISS_MIN_DBM, dtype=np.float32)
    route_points, aligned_noise, skipped_noise = _route_points_for_mode(mode, gps_points, noise_points)
    out_of_bounds = 0
    indoor_filtered = 0
    valid_projected_points = 0
    duplicate_points = 0
    valid_projected_noise_dbm: list[float] = []
    projected_route_points: list[dict[str, Any]] = []
    projected_aligned_points: list[dict[str, Any]] = []
    projected_sparse_points: list[dict[str, Any]] = []
    filtered_noise = sum(1 for point in noise_points if point.filtered) if mode == "gps_n" else 0
    usable_noise = sum(
        1
        for point in route_points
        if isinstance(point, AlignedNoisePoint) and point.noise_floor_db is not None
    )

    for gps_point in gps_points:
        projected_route_points.append(_route_point_payload(gps_point, frame))

    for point in route_points:
        grid, _enu = _latlon_to_grid(point, frame)
        payload = _route_point_payload(point, frame)
        is_empty_noise = isinstance(point, AlignedNoisePoint) and point.noise_floor_db is None
        if not grid.inside_extent or grid.row is None or grid.col is None:
            if not is_empty_noise:
                out_of_bounds += 1
            continue
        row, col = grid.row, grid.col
        if isinstance(point, AlignedNoisePoint):
            projected_aligned_points.append(payload)
            if is_empty_noise:
                continue
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
        "usable_noise": usable_noise,
        "skipped_noise": skipped_noise,
        "filtered_noise": filtered_noise,
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
