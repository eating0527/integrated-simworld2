import json
import logging
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

from app.iss_unet_service import ISS_MAX_DBM, ISS_MIN_DBM, REQUIRED_DATASET_FILES, _canonical_scene, resolve_scene_dataset

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent
SCENE_DIR = BASE_DIR / "static" / "scenes"

GRID_RES = 128
AREA_M = 512.0
FREQUENCY_HZ = 3.5e9
SIONNA_MAX_DEPTH = 10
SIONNA_SAMPLES_PER_TX = 1_000_000
GTX_DB = 0.0
GRX_DB = 0.0
INSERTION_LOSS_DB = 0.0


class SceneUnavailableError(FileNotFoundError):
    pass


@dataclass(frozen=True)
class DatasetTransmitter:
    role: str
    position_px: tuple[int, int]
    ptx_dbm: float
    height_m: float


def _clip_radio_map(values: np.ndarray) -> np.ndarray:
    return np.clip(values.astype(np.float32), ISS_MIN_DBM, ISS_MAX_DBM)


def _dbm_to_w(dbm: np.ndarray | float) -> np.ndarray | float:
    return 10.0 ** ((np.asarray(dbm) - 30.0) / 10.0)


def _w_to_dbm(watts: np.ndarray) -> np.ndarray:
    return 10.0 * np.log10(np.maximum(watts, 1e-30)) + 30.0


def _to_numpy(value: Any) -> np.ndarray:
    if hasattr(value, "detach"):
        value = value.detach()
    if hasattr(value, "cpu"):
        value = value.cpu()
    if hasattr(value, "numpy"):
        return value.numpy()
    return np.array(value)


def resolve_scene_xml(scene: str, scene_dir: Path = SCENE_DIR) -> tuple[str, Path]:
    scene_name = _canonical_scene(scene)
    scene_xml = scene_dir / scene_name / f"{scene_name}.xml"
    if not scene_xml.exists():
        raise SceneUnavailableError(f"Scene XML not found: {scene_xml}")
    return scene_name, scene_xml


def _downsample_to_grid(values: np.ndarray, grid_res: int = GRID_RES) -> np.ndarray:
    values = np.asarray(values, dtype=np.float32)
    if values.shape == (grid_res, grid_res):
        return values
    if values.ndim != 2:
        raise ValueError(f"height map must be 2D, got shape {values.shape}")
    if values.shape[0] >= grid_res and values.shape[1] >= grid_res:
        row_step = max(values.shape[0] // grid_res, 1)
        col_step = max(values.shape[1] // grid_res, 1)
        sampled = values[::row_step, ::col_step]
        if sampled.shape[0] >= grid_res and sampled.shape[1] >= grid_res:
            return sampled[:grid_res, :grid_res].astype(np.float32)
    row_idx = np.linspace(0, values.shape[0] - 1, grid_res).round().astype(int)
    col_idx = np.linspace(0, values.shape[1] - 1, grid_res).round().astype(int)
    return values[np.ix_(row_idx, col_idx)].astype(np.float32)


def extract_building_height_map(scene_xml: Path, grid_res: int = GRID_RES, area_m: float = AREA_M) -> np.ndarray:
    scene_dir = scene_xml.parent
    for filename in ("building_height_512.npy", "2D_Building_Height_Map.npy"):
        source_path = scene_dir / filename
        if source_path.exists():
            return _downsample_to_grid(np.load(source_path), grid_res)
    return rasterize_building_height_from_ply(scene_xml, grid_res=grid_res, area_m=area_m)


def _iter_scene_ply_paths(scene_xml: Path) -> list[Path]:
    scene_dir = scene_xml.parent
    root = ET.parse(scene_xml).getroot()
    paths: list[Path] = []
    for shape in root.iter("shape"):
        if shape.attrib.get("type") != "ply":
            continue
        filename = None
        for child in shape:
            if child.tag == "string" and child.attrib.get("name") == "filename":
                filename = child.attrib.get("value")
                break
        if filename:
            paths.append((scene_dir / filename).resolve())
    return paths


def rasterize_building_height_from_ply(scene_xml: Path, grid_res: int = GRID_RES, area_m: float = AREA_M) -> np.ndarray:
    try:
        import trimesh  # type: ignore
    except ImportError as exc:
        raise RuntimeError("trimesh is required to rasterize building heights from PLY") from exc

    building_map = np.zeros((grid_res, grid_res), dtype=np.float32)
    pixel_size = area_m / grid_res
    for mesh_path in _iter_scene_ply_paths(scene_xml):
        if not mesh_path.exists():
            logger.warning("Scene mesh referenced by XML was not found: %s", mesh_path)
            continue
        loaded = trimesh.load_mesh(str(mesh_path), process=False)
        meshes = list(loaded.geometry.values()) if hasattr(loaded, "geometry") else [loaded]
        for mesh in meshes:
            vertices = np.asarray(getattr(mesh, "vertices", []), dtype=np.float32)
            if vertices.ndim != 2 or vertices.shape[0] == 0 or vertices.shape[1] < 3:
                continue
            min_x, min_y, min_z = np.min(vertices[:, :3], axis=0)
            max_x, max_y, max_z = np.max(vertices[:, :3], axis=0)
            height = float(max_z - min_z)
            if height <= 0.25:
                continue
            x0 = int(np.floor((min_x + area_m / 2.0) / pixel_size))
            x1 = int(np.ceil((max_x + area_m / 2.0) / pixel_size))
            y0 = int(np.floor((area_m / 2.0 - max_y) / pixel_size))
            y1 = int(np.ceil((area_m / 2.0 - min_y) / pixel_size))
            x0 = max(0, min(grid_res - 1, x0))
            x1 = max(0, min(grid_res, x1))
            y0 = max(0, min(grid_res - 1, y0))
            y1 = max(0, min(grid_res, y1))
            if x1 > x0 and y1 > y0:
                building_map[y0:y1, x0:x1] = np.maximum(building_map[y0:y1, x0:x1], height)
    return building_map


def default_transmitters(
    bs_pos: tuple[int, int] = (64, 64),
    jammer_positions: list[tuple[int, int]] | None = None,
    jammer_powers: list[float] | None = None,
    bs_power: float = 40.0,
    bs_height: float = 40.0,
    jammer_height: float = 40.0,
) -> list[DatasetTransmitter]:
    if jammer_positions is None:
        jammer_positions = [(30, 30)]
    if jammer_powers is None:
        jammer_powers = [40.0] * len(jammer_positions)
    if len(jammer_positions) != len(jammer_powers):
        raise ValueError("jammer_positions and jammer_powers must have the same length")
    transmitters = [DatasetTransmitter("desired", bs_pos, float(bs_power), float(bs_height))]
    transmitters.extend(
        DatasetTransmitter("jammer", position, float(power), float(jammer_height))
        for position, power in zip(jammer_positions, jammer_powers)
    )
    return transmitters


def run_sionna_dataset_maps(
    scene_xml: Path,
    transmitters: list[DatasetTransmitter],
    rx_height: float = 1.5,
    area_m: float = AREA_M,
    grid_res: int = GRID_RES,
) -> dict[str, np.ndarray]:
    from sionna.rt import PlanarArray, RadioMapSolver, Receiver, Transmitter, load_scene  # type: ignore

    scene = load_scene(str(scene_xml))
    scene.frequency = FREQUENCY_HZ
    scene.tx_array = PlanarArray(num_rows=1, num_cols=1, vertical_spacing=0.5, horizontal_spacing=0.5, pattern="iso", polarization="V")
    scene.rx_array = PlanarArray(num_rows=1, num_cols=1, vertical_spacing=0.5, horizontal_spacing=0.5, pattern="iso", polarization="V")

    pixel_size = area_m / grid_res
    for index, tx_cfg in enumerate(transmitters):
        x_px, y_px = tx_cfg.position_px
        x_m = (x_px - grid_res / 2.0) * pixel_size
        y_m = -(y_px - grid_res / 2.0) * pixel_size
        scene.add(
            Transmitter(
                name=f"tx_{index}_{tx_cfg.role}",
                position=[x_m, y_m, tx_cfg.height_m],
                orientation=[0.0, 0.0, 0.0],
            )
        )
    scene.add(Receiver(name="rx", position=[0.0, 0.0, rx_height]))

    rm = RadioMapSolver()(
        scene=scene,
        max_depth=SIONNA_MAX_DEPTH,
        samples_per_tx=SIONNA_SAMPLES_PER_TX,
        cell_size=(pixel_size, pixel_size),
        center=[0.0, 0.0, 0.1],
        size=[area_m, area_m],
        orientation=[0.0, 0.0, 0.0],
        refraction=False,
        diffuse_reflection=True,
    )
    path_gain = _to_numpy(rm.path_gain).astype(np.float32)
    path_gain = np.flip(path_gain, axis=1)

    total_gain_lin = 10.0 ** ((GTX_DB + GRX_DB - INSERTION_LOSS_DB) / 10.0)
    powers_w = np.array([_dbm_to_w(tx.ptx_dbm) for tx in transmitters], dtype=np.float64)
    received_w = path_gain * powers_w[:, None, None] * total_gain_lin
    roles = [tx.role for tx in transmitters]
    desired_idx = [idx for idx, role in enumerate(roles) if role == "desired"]
    jammer_idx = [idx for idx, role in enumerate(roles) if role == "jammer"]
    dss_w = np.sum(received_w[desired_idx], axis=0) if desired_idx else np.zeros((grid_res, grid_res), dtype=np.float32)
    iss_w = np.sum(received_w[jammer_idx], axis=0) if jammer_idx else np.zeros((grid_res, grid_res), dtype=np.float32)
    tss_w = dss_w + iss_w
    return {
        "DSS": _clip_radio_map(_w_to_dbm(dss_w)),
        "ISS": _clip_radio_map(_w_to_dbm(iss_w)),
        "TSS": _clip_radio_map(_w_to_dbm(tss_w)),
    }


def _save_radio_map(path: Path, values: np.ndarray, grid_res: int) -> None:
    values = _clip_radio_map(values)
    if values.shape != (grid_res, grid_res):
        raise ValueError(f"{path.name} must be {grid_res}x{grid_res}, got {values.shape}")
    np.save(path, values.astype(np.float32))


def prepare_iss_unet_dataset(
    scene: str,
    scene_dir: Path = SCENE_DIR,
    bs_pos: tuple[int, int] = (64, 64),
    jammer_positions: list[tuple[int, int]] | None = None,
    jammer_powers: list[float] | None = None,
    bs_power: float = 40.0,
    bs_height: float = 40.0,
    jammer_height: float = 40.0,
    rx_height: float = 1.5,
    grid_res: int = GRID_RES,
    area_m: float = AREA_M,
) -> dict[str, Any]:
    scene_name, scene_xml = resolve_scene_xml(scene, scene_dir=scene_dir)
    transmitters = default_transmitters(
        bs_pos=bs_pos,
        jammer_positions=jammer_positions,
        jammer_powers=jammer_powers,
        bs_power=bs_power,
        bs_height=bs_height,
        jammer_height=jammer_height,
    )
    data_dir = scene_xml.parent / "iss_unet_data"
    data_dir.mkdir(parents=True, exist_ok=True)

    building_map = extract_building_height_map(scene_xml, grid_res=grid_res, area_m=area_m)
    if building_map.shape != (grid_res, grid_res):
        raise ValueError(f"building map must be {grid_res}x{grid_res}, got {building_map.shape}")
    np.save(data_dir / f"building_height_{grid_res}.npy", building_map.astype(np.float32))

    radio_maps = run_sionna_dataset_maps(scene_xml, transmitters, rx_height=rx_height, area_m=area_m, grid_res=grid_res)
    _save_radio_map(data_dir / "sionna_dss.npy", radio_maps["DSS"], grid_res)
    _save_radio_map(data_dir / "sionna_iss.npy", radio_maps["ISS"], grid_res)
    _save_radio_map(data_dir / "sionna_tss.npy", radio_maps["TSS"], grid_res)

    meta = {
        "scene": scene_name,
        "scene_xml": str(scene_xml),
        "grid_res": grid_res,
        "area_m": area_m,
        "pixel_size_m": area_m / grid_res,
        "frequency_hz": FREQUENCY_HZ,
        "tx_list": [
            {
                "role": tx.role,
                "position_px": list(tx.position_px),
                "ptx_dbm": tx.ptx_dbm,
                "height_m": tx.height_m,
            }
            for tx in transmitters
        ],
        "rx_height": rx_height,
        "sionna": {
            "max_depth": SIONNA_MAX_DEPTH,
            "samples_per_tx": SIONNA_SAMPLES_PER_TX,
        },
        "outputs": {
            "building_map": f"building_height_{grid_res}.npy",
            "dss": "sionna_dss.npy",
            "iss": "sionna_iss.npy",
            "tss": "sionna_tss.npy",
        },
        "prepared_at": datetime.now().isoformat(),
    }
    (data_dir / "scene_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    dataset = resolve_scene_dataset(scene_name, scene_dir=scene_dir)
    return {
        "success": True,
        "scene": dataset.scene,
        "available": dataset.available,
        "data_dir": str(dataset.data_dir),
        "missing_files": dataset.missing_files,
        "meta_available": dataset.meta_path is not None,
        "outputs": {name: str(dataset.files[name]) for name in REQUIRED_DATASET_FILES},
        "meta": meta,
    }
