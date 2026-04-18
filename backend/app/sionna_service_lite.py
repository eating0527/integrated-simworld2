"""
sionna_service_lite.py
======================
Minimal Sionna RT-based map generation for sim-world-lite.
Extracted from sim-world's sionna_service.py, stripped of all DB / SQLAlchemy
dependencies — devices are passed directly as plain dicts.

Coordinate convention
---------------------
The frontend (Three.js) uses a Y-up right-handed system:
  x → east, y → height (up), z → south

Sionna RT (Mitsuba 3) uses a Z-up right-handed system:
  x → east, y → north, z → height (up)

Conversion: [x_three, y_three, z_three] → [x_three, -z_three, y_three]
i.e. sionna_x = x, sionna_y = -z, sionna_z = y (height)

The RadioMapSolver computes a 2D horizontal map at a given altitude (sionna_z).
"""

import logging
import os
import pathlib
import xml.etree.ElementTree as ET
from typing import List, Optional

import matplotlib
matplotlib.use("Agg")  # non-interactive backend, must be set before pyplot import
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.collections import LineCollection
import numpy as np
from scipy.ndimage import gaussian_filter, maximum_filter

logger = logging.getLogger(__name__)

DEFAULT_TX_POWER_DBM = 80.0
DEFAULT_JAM_POWER_DBM = 80.0

# ---------------------------------------------------------------------------
# Optional heavy imports — deferred so the module can still be imported for
# type-checking even when Sionna / TF are not installed.
# ---------------------------------------------------------------------------

def _import_sionna():
    from sionna.rt import (  # type: ignore
        load_scene,
        Transmitter as SionnaTransmitter,
        Receiver as SionnaReceiver,
        PlanarArray,
        RadioMapSolver,
    )
    return load_scene, SionnaTransmitter, SionnaReceiver, PlanarArray, RadioMapSolver


try:
    from skimage.feature import peak_local_max  # type: ignore
    _HAS_SKIMAGE = True
except ImportError:
    _HAS_SKIMAGE = False
    logger.warning("scikit-image not available; CFAR peak detection will use fallback.")


# ---------------------------------------------------------------------------
# Coordinate helpers
# ---------------------------------------------------------------------------

def threejs_to_sionna(x: float, y: float, z: float):
    """Convert Three.js (x, y_height, z) → Sionna RT (x, y_north, z_height)."""
    return [x, -z, y]


def _load_scene_footprints(scene_xml_path: str) -> tuple[list[dict], Optional[tuple[float, float, float, float]]]:
    """Load 2D mesh outlines from the PLY files referenced by the Sionna scene XML."""
    scene_dir = pathlib.Path(scene_xml_path).resolve().parent
    footprints: list[dict] = []
    bounds: Optional[list[float]] = None

    try:
        import trimesh  # type: ignore

        root = ET.parse(scene_xml_path).getroot()
        for shape in root.iter("shape"):
            if shape.attrib.get("type") != "ply":
                continue

            filename = None
            for child in shape:
                if child.tag == "string" and child.attrib.get("name") == "filename":
                    filename = child.attrib.get("value")
                    break
            if not filename:
                continue

            mesh_path = (scene_dir / filename).resolve()
            if not mesh_path.exists():
                logger.warning("Scene mesh referenced by XML was not found: %s", mesh_path)
                continue

            loaded = trimesh.load_mesh(str(mesh_path), process=False)
            meshes = list(loaded.geometry.values()) if hasattr(loaded, "geometry") else [loaded]
            for mesh in meshes:
                vertices = np.asarray(getattr(mesh, "vertices", []), dtype=float)
                if vertices.ndim != 2 or vertices.shape[0] == 0 or vertices.shape[1] < 3:
                    continue

                min_x, min_y, min_z = np.min(vertices[:, :3], axis=0)
                max_x, max_y, max_z = np.max(vertices[:, :3], axis=0)
                if bounds is None:
                    bounds = [min_x, max_x, min_y, max_y]
                else:
                    bounds[0] = min(bounds[0], min_x)
                    bounds[1] = max(bounds[1], max_x)
                    bounds[2] = min(bounds[2], min_y)
                    bounds[3] = max(bounds[3], max_y)

                lines = np.empty((0, 2, 2), dtype=float)
                edges = np.asarray(getattr(mesh, "edges_unique", []), dtype=int)
                if edges.ndim == 2 and edges.shape[1] == 2 and edges.shape[0] > 0:
                    lines = vertices[edges, :2]

                footprints.append(
                    {
                        "filename": str(mesh_path.relative_to(scene_dir)),
                        "bounds": (float(min_x), float(max_x), float(min_y), float(max_y)),
                        "height": float(max_z - min_z),
                        "lines": lines,
                    }
                )
    except Exception:
        logger.exception("Failed to load scene footprints for map overlay")

    if bounds is None:
        return footprints, None
    return footprints, (float(bounds[0]), float(bounds[1]), float(bounds[2]), float(bounds[3]))


def _coord_edges(coords: np.ndarray, fallback_step: float) -> tuple[float, float]:
    """Convert sorted cell-center coordinates into image-edge coordinates."""
    coords = np.asarray(coords, dtype=float)
    if coords.size == 0:
        return 0.0, float(fallback_step)
    if coords.size == 1:
        half = max(float(fallback_step), 1.0) / 2.0
        return float(coords[0] - half), float(coords[0] + half)

    diffs = np.abs(np.diff(coords))
    diffs = diffs[diffs > 0]
    step = float(np.median(diffs)) if diffs.size else max(float(fallback_step), 1.0)
    half = step / 2.0
    return float(coords[0] - half), float(coords[-1] + half)


def _expand_bounds(bounds: tuple[float, float, float, float], padding_ratio: float = 0.02) -> tuple[float, float, float, float]:
    min_x, max_x, min_y, max_y = bounds
    span = max(max_x - min_x, max_y - min_y, 1.0)
    pad = span * padding_ratio
    return min_x - pad, max_x + pad, min_y - pad, max_y + pad


def _draw_scene_footprints(ax, footprints: list[dict]) -> None:
    """Overlay ground/building outlines so the generated map shows full scene context."""
    for footprint in sorted(footprints, key=lambda item: item["height"] > 0.25):
        min_x, max_x, min_y, max_y = footprint["bounds"]
        is_ground = footprint["height"] <= 0.25

        if is_ground:
            rect = mpatches.Rectangle(
                (min_x, min_y),
                max_x - min_x,
                max_y - min_y,
                fill=False,
                edgecolor="white",
                linewidth=1.2,
                alpha=0.65,
                zorder=2,
            )
            ax.add_patch(rect)
            continue

        lines = footprint["lines"]
        if isinstance(lines, np.ndarray) and lines.size:
            ax.add_collection(
                LineCollection(
                    lines,
                    colors="white",
                    linewidths=0.35,
                    alpha=0.55,
                    zorder=3,
                )
            )
        else:
            rect = mpatches.Rectangle(
                (min_x, min_y),
                max_x - min_x,
                max_y - min_y,
                fill=False,
                edgecolor="white",
                linewidth=0.5,
                alpha=0.55,
                zorder=3,
            )
            ax.add_patch(rect)


# ---------------------------------------------------------------------------
# Core map generation
# ---------------------------------------------------------------------------

ANTENNA_CONFIG = {
    "num_rows": 1,
    "num_cols": 1,
    "vertical_spacing": 0.5,
    "horizontal_spacing": 0.5,
    "pattern": "iso",
    "polarization": "V",
}


def generate_maps(
    *,
    scene_xml_path: str,
    devices: List[dict],
    output_dir: str,
    scene_name: str = "ntpu",
    map_type: str = "iss",          # "iss" | "tss" | "cfar"
    cell_size: float = 4.0,
    map_size: tuple = (512, 512),
    samples_per_tx: int = 10 ** 6,  # reduced for lite version
    altitude: float = 1.5,          # map altitude in metres (Sionna z)
    gaussian_sigma: float = 1.0,
    cfar_min_distance: int = 3,
    cfar_threshold_percentile: float = 99.5,
    frequency_hz: float = 1.5e9,
    overlay_scene: bool = False,
) -> str:
    """
    Run Sionna RadioMapSolver and generate the requested map type.

    Parameters
    ----------
    scene_xml_path : str
        Absolute path to the Sionna XML scene file.
    devices : list of dict
        Each dict: {name, role ('tx'|'rx'|'jammer'), x, y, z, power_dbm?}
        Coordinates are in Three.js convention.
    output_dir : str
        Directory in which to write the PNG (e.g. .../public/maps/ntpu/).
    map_type : str
        "iss"  → Interference Signal Strength heatmap
        "tss"  → Total Signal Strength heatmap
        "cfar" → ISS heatmap with CFAR peak markers overlaid
    Returns
    -------
    str  : absolute path of the written PNG file.
    """
    (
        load_scene,
        SionnaTransmitter,
        SionnaReceiver,
        PlanarArray,
        RadioMapSolver,
    ) = _import_sionna()

    os.makedirs(output_dir, exist_ok=True)
    scene_footprints: list[dict] = []
    scene_bounds = None
    if overlay_scene:
        scene_footprints, scene_bounds = _load_scene_footprints(scene_xml_path)

    if overlay_scene and scene_bounds is not None:
        logger.info(
            "Loaded %d scene footprint mesh(es), scene bounds x=[%.1f, %.1f], y=[%.1f, %.1f]",
            len(scene_footprints),
            scene_bounds[0],
            scene_bounds[1],
            scene_bounds[2],
            scene_bounds[3],
        )

    # -----------------------------------------------------------------------
    # Separate devices by role
    # -----------------------------------------------------------------------
    tx_devices   = [d for d in devices if d["role"] == "tx"]
    rx_devices   = [d for d in devices if d["role"] == "rx"]
    jam_devices  = [d for d in devices if d["role"] == "jammer"]

    if not rx_devices:
        raise ValueError("At least one RX device is required.")

    rx = rx_devices[0]  # only one RX (UAV)

    # -----------------------------------------------------------------------
    # Load Sionna scene
    # -----------------------------------------------------------------------
    logger.info("Loading Sionna scene: %s", scene_xml_path)
    scene = load_scene(scene_xml_path)

    scene.tx_array = PlanarArray(**ANTENNA_CONFIG)
    scene.rx_array = PlanarArray(**ANTENNA_CONFIG)
    scene.frequency = frequency_hz

    # Clear any existing objects in the scene
    for name in list(scene.transmitters):
        scene.remove(name)
    for name in list(scene.receivers):
        scene.remove(name)

    # -----------------------------------------------------------------------
    # Add transmitters (TX + Jammer)
    # -----------------------------------------------------------------------
    all_tx_entries = []   # list of (SionnaTransmitter, role_str)
    idx_desired: List[int] = []
    idx_jammer: List[int] = []

    for i, d in enumerate(tx_devices):
        pos_sionna = threejs_to_sionna(d["x"], d["y"], d["z"])
        power = d.get("power_dbm", DEFAULT_TX_POWER_DBM)
        tx = SionnaTransmitter(
            name=d["name"],
            position=pos_sionna,
            orientation=[0.0, 0.0, 0.0],
            power_dbm=float(power),
        )
        tx.role = "desired"
        scene.add(tx)
        all_tx_entries.append(tx)
        idx_desired.append(len(all_tx_entries) - 1)
        logger.info("Added TX '%s' at Sionna %s, %.1f dBm", d["name"], pos_sionna, power)

    for i, d in enumerate(jam_devices):
        pos_sionna = threejs_to_sionna(d["x"], d["y"], d["z"])
        power = d.get("power_dbm", DEFAULT_JAM_POWER_DBM)
        jammer = SionnaTransmitter(
            name=d["name"],
            position=pos_sionna,
            orientation=[0.0, 0.0, 0.0],
            power_dbm=float(power),
        )
        jammer.role = "jammer"
        scene.add(jammer)
        all_tx_entries.append(jammer)
        idx_jammer.append(len(all_tx_entries) - 1)
        logger.info("Added Jammer '%s' at Sionna %s, %.1f dBm", d["name"], pos_sionna, power)

    # -----------------------------------------------------------------------
    # Add receiver
    # -----------------------------------------------------------------------
    rx_pos_sionna = threejs_to_sionna(rx["x"], rx["y"], rx["z"])
    rx_obj = SionnaReceiver(name=rx["name"], position=rx_pos_sionna)
    scene.add(rx_obj)
    logger.info("Added RX '%s' at Sionna %s", rx["name"], rx_pos_sionna)

    # -----------------------------------------------------------------------
    # Run RadioMapSolver  (no center/size → auto-use scene bounding box)
    # -----------------------------------------------------------------------
    logger.info(
        "Running RadioMapSolver: cell_size=%s, samples=%s",
        cell_size, samples_per_tx,
    )
    rm_solver = RadioMapSolver()
    rm = rm_solver(
        scene,
        max_depth=5,
        samples_per_tx=samples_per_tx,
        cell_size=(cell_size, cell_size),
        refraction=False,
        specular_reflection=True,
        diffuse_reflection=True,
    )

    # -----------------------------------------------------------------------
    # Extract RSS per transmitter
    # -----------------------------------------------------------------------
    # rm.rss shape: (num_tx, H, W)  — power in Watts per cell
    WSS = rm.rss[:].numpy()   # (num_tx, H, W)

    TSS = np.sum(WSS, axis=0)  # Total Signal Strength

    DSS = (
        np.sum(WSS[idx_desired, :, :], axis=0)
        if idx_desired
        else np.zeros_like(TSS)
    )
    ISS = (
        np.sum(WSS[idx_jammer, :, :], axis=0)
        if idx_jammer
        else np.zeros_like(TSS)
    )

    # Convert to dBm
    def to_dbm(arr: np.ndarray) -> np.ndarray:
        return 10.0 * np.log10(np.maximum(arr, 1e-12) / 1e-3)

    iss_dbm = to_dbm(ISS)
    tss_dbm = to_dbm(TSS)

    # Cell centres for axis labels
    # Sionna 1.x: cell_centers shape is (num_cells_y, num_cells_x, 2)
    cc = rm.cell_centers.numpy()
    # Flatten to get unique sorted axis values
    x_coords = np.unique(cc[:, :, 0])
    y_coords = np.unique(cc[:, :, 1])

    # -----------------------------------------------------------------------
    # CFAR peak detection (on smoothed ISS)
    # -----------------------------------------------------------------------
    iss_smooth = gaussian_filter(iss_dbm, sigma=gaussian_sigma)
    peak_coords_list = []

    if map_type in ("cfar", "iss"):
        peak_coords_list = _detect_cfar_peaks(
            iss_smooth,
            min_distance=cfar_min_distance,
            threshold_percentile=cfar_threshold_percentile,
        )

    # -----------------------------------------------------------------------
    # Select data for requested map type
    # -----------------------------------------------------------------------
    if map_type == "iss":
        data = iss_smooth
        title = f"ISS Map — {scene_name.upper()}"
        cbar_label = "ISS (dBm)"
        cmap = "hot"
    elif map_type == "tss":
        data = gaussian_filter(tss_dbm, sigma=gaussian_sigma)
        title = f"TSS Map — {scene_name.upper()}"
        cbar_label = "TSS (dBm)"
        cmap = "viridis"
    else:  # cfar
        data = iss_smooth
        title = f"ISS+CFAR Map — {scene_name.upper()}"
        cbar_label = "ISS (dBm)"
        cmap = "hot"

    # -----------------------------------------------------------------------
    # Plot
    # -----------------------------------------------------------------------
    # Use cell edges, not cell centers, so the outer half-cell is not clipped.
    heatmap_x_min, heatmap_x_max = _coord_edges(x_coords, cell_size)
    heatmap_y_min, heatmap_y_max = _coord_edges(y_coords, cell_size)

    # Use the union of the radio-map extent, optional scene footprint, and device points.
    plot_min_x, plot_max_x = heatmap_x_min, heatmap_x_max
    plot_min_y, plot_max_y = heatmap_y_min, heatmap_y_max
    if overlay_scene and scene_bounds is not None:
        plot_min_x = min(plot_min_x, scene_bounds[0])
        plot_max_x = max(plot_max_x, scene_bounds[1])
        plot_min_y = min(plot_min_y, scene_bounds[2])
        plot_max_y = max(plot_max_y, scene_bounds[3])

    device_xy = [
        threejs_to_sionna(d["x"], d["y"], d["z"])[:2]
        for d in [*tx_devices, *jam_devices, rx]
    ]
    for x_val, y_val in device_xy:
        plot_min_x = min(plot_min_x, x_val)
        plot_max_x = max(plot_max_x, x_val)
        plot_min_y = min(plot_min_y, y_val)
        plot_max_y = max(plot_max_y, y_val)

    plot_min_x, plot_max_x, plot_min_y, plot_max_y = _expand_bounds(
        (plot_min_x, plot_max_x, plot_min_y, plot_max_y)
    )
    x_range = abs(plot_max_x - plot_min_x) or 1
    y_range = abs(plot_max_y - plot_min_y) or 1
    fig_w = 9
    fig_h = max(6, fig_w * y_range / x_range)
    fig, ax = plt.subplots(figsize=(fig_w, fig_h))
    im = ax.imshow(
        data,
        origin="lower",
        aspect="equal",
        cmap=cmap,
        alpha=0.88,
        zorder=1,
        extent=[heatmap_x_min, heatmap_x_max, heatmap_y_min, heatmap_y_max],
    )
    if overlay_scene:
        _draw_scene_footprints(ax, scene_footprints)
    plt.colorbar(im, ax=ax, label=cbar_label)
    ax.set_title(title, fontsize=13)
    ax.set_xlabel("X (m)")
    ax.set_ylabel("Y (m)")
    ax.set_xlim(plot_min_x, plot_max_x)
    ax.set_ylim(plot_min_y, plot_max_y)
    ax.set_aspect("equal", adjustable="box")

    # Mark TX, Jammer, RX positions on the map
    for d in tx_devices:
        ps = threejs_to_sionna(d["x"], d["y"], d["z"])
        ax.plot(ps[0], ps[1], "b^", markersize=10, label="TX", zorder=5)
    for d in jam_devices:
        ps = threejs_to_sionna(d["x"], d["y"], d["z"])
        ax.plot(ps[0], ps[1], "rs", markersize=10, label="Jammer", zorder=5)
    rx_ps = threejs_to_sionna(rx["x"], rx["y"], rx["z"])
    ax.plot(rx_ps[0], rx_ps[1], "g*", markersize=12, label="RX (UAV)", zorder=5)

    # Overlay CFAR peaks
    if map_type == "cfar" and peak_coords_list:
        for row, col in peak_coords_list:
            if 0 <= col < len(x_coords) and 0 <= row < len(y_coords):
                ax.plot(
                    x_coords[col],
                    y_coords[row],
                    "cx",
                    markersize=12,
                    markeredgewidth=2,
                    zorder=6,
                    label="CFAR Peak",
                )

    # Deduplicate legend
    handles, labels = ax.get_legend_handles_labels()
    by_label = dict(zip(labels, handles))
    ax.legend(by_label.values(), by_label.keys(), loc="upper right", fontsize=8)

    # -----------------------------------------------------------------------
    # Save to memory buffer (avoid disk I/O race conditions)
    # -----------------------------------------------------------------------
    import io as _io
    buf = _io.BytesIO()
    fig.savefig(buf, format="png", dpi=120, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    image_bytes = buf.read()
    buf.close()

    # Also write to disk for caching / debugging
    filename_map = {"iss": "iss_map.png", "tss": "tss_map.png", "cfar": "cfar_map.png"}
    out_path = os.path.join(output_dir, filename_map[map_type])
    with open(out_path, "wb") as f:
        f.write(image_bytes)
    logger.info("Saved %s map to %s (%d bytes)", map_type.upper(), out_path, len(image_bytes))
    return image_bytes


# ---------------------------------------------------------------------------
# CFAR helpers
# ---------------------------------------------------------------------------

def _detect_cfar_peaks(
    iss_smooth: np.ndarray,
    min_distance: int = 3,
    threshold_percentile: float = 99.5,
) -> List[tuple]:
    """Return list of (row, col) peak coordinates detected by 2D-CFAR."""
    if _HAS_SKIMAGE:
        threshold_abs = np.percentile(iss_smooth, threshold_percentile)
        coords = peak_local_max(  # type: ignore[name-defined]
            iss_smooth,
            min_distance=min_distance,
            threshold_abs=float(threshold_abs),
        )
        return [(int(r), int(c)) for r, c in coords]
    else:
        # Fallback: sliding-window maximum
        local_max = maximum_filter(iss_smooth, size=max(3, min_distance * 2 + 1))
        threshold = np.percentile(iss_smooth, threshold_percentile)
        peak_mask = (iss_smooth == local_max) & (iss_smooth >= threshold)
        coords = np.argwhere(peak_mask)
        return [(int(r), int(c)) for r, c in coords]
