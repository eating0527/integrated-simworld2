"""The single local coordinate contract shared by backend scene services."""

from dataclasses import dataclass
import math
from typing import Any


FRAME_VERSION = 1
AXIS = "ENU"
UNITS = "m"
MIN_E = -256.0
MAX_E = 256.0
MIN_N = -256.0
MAX_N = 256.0
GRID_ROWS = 128
GRID_COLS = 128
PIXEL_SIZE_E_M = 4.0
PIXEL_SIZE_N_M = 4.0
DISPLAY_MARGIN_M = 32.0


@dataclass(frozen=True)
class SceneFrame:
    origin_lat: float
    origin_lon: float
    origin_alt_m: float
    frame_id: str = "scene-unknown"
    alt_mode: str = "amsl"

    def __post_init__(self) -> None:
        if not self.frame_id:
            raise ValueError("frame_id is required")
        if self.alt_mode not in {"amsl", "relative"}:
            raise ValueError("alt_mode must be 'amsl' or 'relative'")
        if not all(math.isfinite(float(value)) for value in (self.origin_lat, self.origin_lon, self.origin_alt_m)):
            raise ValueError("SceneFrame origin must be finite")
        if not -90.0 <= float(self.origin_lat) <= 90.0:
            raise ValueError("origin_lat must be between -90 and 90")
        if not -180.0 <= float(self.origin_lon) <= 180.0:
            raise ValueError("origin_lon must be between -180 and 180")

    @property
    def extent(self) -> dict[str, float]:
        return {"min_e": MIN_E, "max_e": MAX_E, "min_n": MIN_N, "max_n": MAX_N}

    @property
    def grid(self) -> dict[str, float | int]:
        return {
            "rows": GRID_ROWS,
            "cols": GRID_COLS,
            "pixel_size_e_m": PIXEL_SIZE_E_M,
            "pixel_size_n_m": PIXEL_SIZE_N_M,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "frame_version": FRAME_VERSION,
            "frame_id": self.frame_id,
            "origin": {
                "lat": float(self.origin_lat),
                "lon": float(self.origin_lon),
                "alt_m": float(self.origin_alt_m),
            },
            "alt_mode": self.alt_mode,
            "axis": AXIS,
            "units": UNITS,
            "extent": self.extent,
            "display_margin_m": DISPLAY_MARGIN_M,
            "grid": self.grid,
        }


@dataclass(frozen=True)
class GridPoint:
    row: int | None
    col: int | None
    inside_extent: bool
    displayable: bool

    def __iter__(self):
        yield self.row
        yield self.col

    def to_dict(self) -> dict[str, Any]:
        return {
            "row": self.row,
            "col": self.col,
            "inside_extent": self.inside_extent,
            "displayable": self.displayable,
        }


def _meters_per_degree(lat: float) -> tuple[float, float]:
    meters_per_degree_lat = 111320.0
    meters_per_degree_lon = max(1.0, meters_per_degree_lat * math.cos(math.radians(lat)))
    return meters_per_degree_lat, meters_per_degree_lon


def gps_to_enu(
    lat: float,
    lon: float,
    alt: float,
    frame: SceneFrame,
    alt_mode: str = "amsl",
) -> tuple[float, float, float]:
    if alt_mode not in {"amsl", "relative"}:
        raise ValueError("alt_mode must be 'amsl' or 'relative'")
    meters_per_degree_lat, meters_per_degree_lon = _meters_per_degree(frame.origin_lat)
    east_m = (float(lon) - frame.origin_lon) * meters_per_degree_lon
    north_m = (float(lat) - frame.origin_lat) * meters_per_degree_lat
    up_m = float(alt) - frame.origin_alt_m if alt_mode == "amsl" else float(alt)
    return float(east_m), float(north_m), float(up_m)


def enu_to_gps(
    east_m: float,
    north_m: float,
    up_m: float,
    frame: SceneFrame,
    alt_mode: str = "amsl",
) -> tuple[float, float, float]:
    if alt_mode not in {"amsl", "relative"}:
        raise ValueError("alt_mode must be 'amsl' or 'relative'")
    meters_per_degree_lat, meters_per_degree_lon = _meters_per_degree(frame.origin_lat)
    lat = frame.origin_lat + float(north_m) / meters_per_degree_lat
    lon = frame.origin_lon + float(east_m) / meters_per_degree_lon
    alt = float(up_m) + frame.origin_alt_m if alt_mode == "amsl" else float(up_m)
    return float(lat), float(lon), float(alt)


def enu_to_three(east_m: float, north_m: float, up_m: float) -> tuple[float, float, float]:
    return float(east_m), float(up_m), float(-north_m)


def enu_to_sionna(east_m: float, north_m: float, up_m: float) -> tuple[float, float, float]:
    return float(east_m), float(north_m), float(up_m)


def enu_to_grid(east_m: float, north_m: float, up_m: float, frame: SceneFrame) -> GridPoint:
    east = float(east_m)
    north = float(north_m)
    inside = MIN_E <= east < MAX_E and MIN_N <= north < MAX_N
    displayable = (
        MIN_E - DISPLAY_MARGIN_M <= east < MAX_E + DISPLAY_MARGIN_M
        and MIN_N - DISPLAY_MARGIN_M <= north < MAX_N + DISPLAY_MARGIN_M
    )
    if not inside:
        return GridPoint(None, None, False, displayable)
    row = min(GRID_ROWS - 1, math.floor((MAX_N - north) / PIXEL_SIZE_N_M))
    col = min(GRID_COLS - 1, math.floor((east - MIN_E) / PIXEL_SIZE_E_M))
    return GridPoint(int(row), int(col), True, displayable)


def grid_to_enu(row: int, col: int, frame: SceneFrame) -> tuple[float, float, float]:
    row = int(row)
    col = int(col)
    if not 0 <= row < GRID_ROWS or not 0 <= col < GRID_COLS:
        raise ValueError("grid row/col outside SceneFrame extent")
    east = MIN_E + (col + 0.5) * PIXEL_SIZE_E_M
    north = MAX_N - (row + 0.5) * PIXEL_SIZE_N_M
    return float(east), float(north), 0.0


def scene_frame_from_metadata(metadata: dict[str, Any]) -> SceneFrame:
    raw = metadata.get("frame") if isinstance(metadata, dict) and "frame" in metadata else metadata
    if not isinstance(raw, dict):
        raise ValueError("scene metadata must include a SceneFrame under 'frame'")
    try:
        origin = raw["origin"]
        extent = raw["extent"]
        grid = raw["grid"]
        frame = SceneFrame(
            frame_id=str(raw["frame_id"]),
            origin_lat=float(origin["lat"]),
            origin_lon=float(origin["lon"]),
            origin_alt_m=float(origin["alt_m"]),
            alt_mode=str(raw.get("alt_mode", "amsl")),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("invalid SceneFrame metadata") from exc
    if raw.get("frame_version") != FRAME_VERSION or raw.get("axis") != AXIS or raw.get("units") != UNITS:
        raise ValueError("unsupported SceneFrame metadata")
    if extent != frame.extent or grid != frame.grid or raw.get("display_margin_m") != DISPLAY_MARGIN_M:
        raise ValueError("SceneFrame metadata must use fixed extent and grid")
    return frame


def validate_scene_frame(metadata: dict[str, Any]) -> SceneFrame:
    return scene_frame_from_metadata(metadata)
