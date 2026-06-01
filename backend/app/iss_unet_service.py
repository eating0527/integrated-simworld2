import io
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent
SCENE_DIR = BASE_DIR / "static" / "scenes"
OUTPUT_DIR = BASE_DIR / "static" / "images"
MODEL_ARTIFACT_PATH = BASE_DIR / "model_artifacts" / "best_iss_reconstruction_model.pth"

REQUIRED_DATASET_FILES = (
    "building_height_128.npy",
    "sionna_dss.npy",
    "sionna_iss.npy",
    "sionna_tss.npy",
)

ISS_MIN_DBM = -140.0
ISS_MAX_DBM = -35.0
BUILDING_MAX_M = 60.0
ISS_UNET_MODE_LABELS = {
    "sim": "Sim",
    "gps": "GPS",
    "gps_n": "GPS with Noise",
}


def result_image_url(filename: str) -> str:
    return f"/api/iss-unet/images/{filename}"


@dataclass(frozen=True)
class SceneDataset:
    scene: str
    data_dir: Path
    files: dict[str, Path]
    missing_files: list[str]
    meta_path: Path | None = None

    @property
    def available(self) -> bool:
        return not self.missing_files


@dataclass(frozen=True)
class ISSUNetCFARParams:
    enabled: bool = True
    guard_cells: int = 2
    training_cells: int = 4
    pfa: float = 1e-4
    os_rank: float = 0.75
    min_threshold_dbm: float = -50.0


def _canonical_scene(scene: str) -> str:
    scene_id = scene.strip()
    if not scene_id:
        raise ValueError("scene is required")
    if any(part in scene_id for part in ("/", "\\", "..")):
        raise ValueError(f"Invalid scene id: {scene_id}")
    builtins = {"ntpu": "NTPU", "nycu": "NYCU"}
    return builtins.get(scene_id.lower(), scene_id.upper())


def resolve_scene_dataset(scene: str, scene_dir: Path = SCENE_DIR) -> SceneDataset:
    scene_name = _canonical_scene(scene)
    data_dir = scene_dir / scene_name / "iss_unet_data"
    files = {name: data_dir / name for name in REQUIRED_DATASET_FILES}
    missing = [name for name, path in files.items() if not path.exists()]
    meta_path = data_dir / "scene_meta.json"
    return SceneDataset(
        scene=scene_name,
        data_dir=data_dir,
        files=files,
        missing_files=missing,
        meta_path=meta_path if meta_path.exists() else None,
    )


def iss_unet_status() -> dict[str, Any]:
    datasets = {}
    for scene in ("NTPU", "NYCU"):
        dataset = resolve_scene_dataset(scene)
        datasets[scene] = {
            "available": dataset.available,
            "data_dir": str(dataset.data_dir),
            "missing_files": dataset.missing_files,
            "meta_available": dataset.meta_path is not None,
        }

    model_available = MODEL_ARTIFACT_PATH.exists()
    try:
        import torch  # noqa: F401

        torch_available = True
        torch_error = None
    except Exception as exc:
        torch_available = False
        torch_error = str(exc)

    return {
        "available": model_available and torch_available,
        "model": {
            "available": model_available,
        },
        "torch": {
            "available": torch_available,
            "error": torch_error,
        },
        "datasets": datasets,
    }


def _clip_radio_map(values: np.ndarray) -> np.ndarray:
    return np.clip(values.astype(np.float32), ISS_MIN_DBM, ISS_MAX_DBM)


def _normalize_radio_map(values: np.ndarray) -> np.ndarray:
    return np.clip((values - ISS_MIN_DBM) / (ISS_MAX_DBM - ISS_MIN_DBM), 0.0, 1.0)


def _denormalize_iss(values: np.ndarray) -> np.ndarray:
    return values * (ISS_MAX_DBM - ISS_MIN_DBM) + ISS_MIN_DBM


def _normalize_sparse_ratio(sparse_ratio: float) -> float:
    sparse_ratio = float(sparse_ratio)
    if not np.isfinite(sparse_ratio):
        raise ValueError("sparse_ratio must be finite")
    return float(np.clip(sparse_ratio, 0.0, 1.0))


def sparse_ratio_label(sparse_ratio: float) -> str:
    percent = _normalize_sparse_ratio(sparse_ratio) * 100.0
    if np.isclose(percent, round(percent)):
        value = str(int(round(percent)))
    else:
        value = f"{percent:.6f}".rstrip("0").rstrip(".").replace(".", "p")
    return f"ratio_{value}"


def load_scene_arrays(dataset: SceneDataset) -> dict[str, np.ndarray]:
    arrays = {
        "building": np.load(dataset.files["building_height_128.npy"]).astype(np.float32),
        "dss": _clip_radio_map(np.load(dataset.files["sionna_dss.npy"])),
        "iss": _clip_radio_map(np.load(dataset.files["sionna_iss.npy"])),
        "tss": _clip_radio_map(np.load(dataset.files["sionna_tss.npy"])),
    }
    shape = arrays["building"].shape
    if shape != (128, 128):
        raise ValueError(f"building_height_128.npy must be 128x128, got {shape}")
    for name, value in arrays.items():
        if value.shape != shape:
            raise ValueError(f"{name} shape {value.shape} does not match building map shape {shape}")
    return arrays


def create_sparse_sample(
    iss_gt: np.ndarray,
    building_map: np.ndarray,
    sparse_ratio: float = 0.2,
    seed: int = 41,
) -> tuple[np.ndarray, np.ndarray]:
    sparse_ratio = _normalize_sparse_ratio(sparse_ratio)
    outdoor_mask = (building_map <= 3.0).astype(np.float32)
    sparse_mask = np.zeros_like(outdoor_mask, dtype=np.float32)
    outdoor_indices = np.argwhere(outdoor_mask > 0.5)
    if len(outdoor_indices) == 0:
        return sparse_mask, outdoor_mask

    n_sparse = int(len(outdoor_indices) * sparse_ratio)
    n_sparse = min(n_sparse, len(outdoor_indices))
    if n_sparse == 0:
        return sparse_mask, outdoor_mask
    rng = np.random.default_rng(seed)
    selected = outdoor_indices[rng.choice(len(outdoor_indices), size=n_sparse, replace=False)]
    sparse_mask[selected[:, 0], selected[:, 1]] = 1.0
    return sparse_mask, outdoor_mask


def build_model_input(
    arrays: dict[str, np.ndarray],
    sparse_ratio: float,
    seed: int = 41,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    sparse_mask, outdoor_mask = create_sparse_sample(
        arrays["iss"],
        arrays["building"],
        sparse_ratio=sparse_ratio,
        seed=seed,
    )
    building_norm = np.clip(arrays["building"] / BUILDING_MAX_M, 0.0, 1.0)
    iss_sparse = _normalize_radio_map(arrays["iss"]) * sparse_mask
    dss_norm = _normalize_radio_map(arrays["dss"])
    inputs = np.stack(
        [building_norm, iss_sparse, sparse_mask, outdoor_mask, dss_norm],
        axis=0,
    ).astype(np.float32)
    return inputs, sparse_mask, outdoor_mask


def _load_model(device: str):
    import torch

    from app.model_iss_unet import ISS_UNet

    torch_device = torch.device(device if device == "cuda" and torch.cuda.is_available() else "cpu")
    model = ISS_UNet(n_channels=5, n_classes=1, bilinear=False, use_data_consistency=True)
    checkpoint = torch.load(MODEL_ARTIFACT_PATH, map_location=torch_device, weights_only=False)
    state_dict = checkpoint.get("model_state_dict", checkpoint)
    model.load_state_dict(state_dict)
    model.to(torch_device)
    model.eval()
    return model, torch_device


def _render_reconstructed_png(reconstructed_iss: np.ndarray, mode_label: str = "Sim") -> bytes:
    fig, ax = plt.subplots(figsize=(5, 5))
    im = ax.imshow(reconstructed_iss, cmap="jet", origin="upper", vmin=-140, vmax=-40)
    ax.set_title("ISS_UNET Reconstructed ISS")
    fig.suptitle(f"ISS_UNET - {mode_label}")
    ax.axis("off")
    plt.colorbar(im, ax=ax, label="Power (dBm)", shrink=0.8)
    fig.tight_layout()
    return _figure_to_png(fig)


def _render_comparison_png(
    arrays: dict[str, np.ndarray],
    reconstructed_iss: np.ndarray,
    sparse_mask: np.ndarray,
    outdoor_mask: np.ndarray,
    sparse_ratio: float,
    mode_label: str = "Sim",
    sparse_values_dbm: np.ndarray | None = None,
) -> bytes:
    error = np.abs(reconstructed_iss - arrays["iss"])
    outdoor_pixels = outdoor_mask > 0.5
    mae = float(error[outdoor_pixels].mean()) if np.any(outdoor_pixels) else 0.0

    fig, axes = plt.subplots(2, 3, figsize=(15, 10))
    sparse_source = arrays["iss"] if sparse_values_dbm is None else sparse_values_dbm
    sparse_title = f"Sparse ISS Input ({sparse_ratio * 100:.0f}%)" if mode_label == "Sim" else f"Sparse ISS Input ({mode_label})"
    sparse_display = np.where(sparse_mask > 0.5, sparse_source, ISS_MIN_DBM)
    panels = [
        (arrays["building"], "Building Height Map", "gray", None, None, "Height (m)"),
        (sparse_display, sparse_title, "jet", -140, -40, "Power (dBm)"),
        (arrays["iss"], "Ground Truth ISS", "jet", -140, -40, "Power (dBm)"),
        (reconstructed_iss, "Reconstructed ISS", "jet", -140, -40, "Power (dBm)"),
        (np.where(outdoor_pixels, error, 0.0), f"Error (Outdoor MAE: {mae:.2f} dB)", "Reds", 0, 10, "Error (dB)"),
        (outdoor_mask, "Outdoor Mask", "gray", 0, 1, None),
    ]
    for ax, (data, title, cmap, vmin, vmax, label) in zip(axes.flat, panels):
        im = ax.imshow(data, cmap=cmap, origin="upper", vmin=vmin, vmax=vmax)
        ax.set_title(title)
        ax.axis("off")
        if label:
            plt.colorbar(im, ax=ax, label=label, shrink=0.75)
    fig.suptitle(f"ISS_UNET - {mode_label}")
    fig.tight_layout()
    return _figure_to_png(fig)


def _figure_to_png(fig) -> bytes:
    buffer = io.BytesIO()
    fig.savefig(buffer, format="png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    return buffer.getvalue()


def _dbm_to_linear(dbm: np.ndarray) -> np.ndarray:
    return 10 ** (dbm / 10.0)


def _linear_to_dbm(linear: np.ndarray) -> np.ndarray:
    return 10 * np.log10(np.clip(linear, 1e-14, None))


def _cfar_detect(
    signal_map: np.ndarray,
    outdoor_mask: np.ndarray,
    params: ISSUNetCFARParams,
) -> dict[str, Any]:
    h, w = signal_map.shape
    signal = _dbm_to_linear(signal_map)
    detection_map = np.zeros((h, w), dtype=np.float32)
    threshold_map = np.full((h, w), np.nan, dtype=np.float32)
    window_half = params.guard_cells + params.training_cells

    for row in range(window_half, h - window_half):
        for col in range(window_half, w - window_half):
            if outdoor_mask[row, col] < 0.5:
                continue
            samples = []
            for r in range(row - window_half, row + window_half + 1):
                for c in range(col - window_half, col + window_half + 1):
                    if abs(r - row) <= params.guard_cells and abs(c - col) <= params.guard_cells:
                        continue
                    if outdoor_mask[r, c] > 0.5:
                        samples.append(signal[r, c])
            if len(samples) < 4:
                continue
            samples.sort()
            rank = max(0, min(int(len(samples) * params.os_rank), len(samples) - 1))
            noise = samples[rank]
            alpha = len(samples) * (params.pfa ** (-1.0 / len(samples)) - 1.0)
            threshold_dbm = float(_linear_to_dbm(alpha * noise))
            threshold_map[row, col] = threshold_dbm
            if signal_map[row, col] >= max(threshold_dbm, params.min_threshold_dbm):
                detection_map[row, col] = 1.0

    clusters = _cluster_detections(detection_map, signal_map)
    return {
        "detection_map": detection_map,
        "threshold_map": threshold_map,
        "clusters": clusters,
        "detections": [
            {"row": int(row), "col": int(col), "power_dbm": float(signal_map[row, col])}
            for row, col in np.argwhere(detection_map > 0.5)
        ],
    }


def _cluster_detections(detection_map: np.ndarray, signal_map: np.ndarray) -> list[dict[str, Any]]:
    visited = np.zeros_like(detection_map, dtype=bool)
    clusters = []
    h, w = detection_map.shape
    for start_row, start_col in np.argwhere(detection_map > 0.5):
        if visited[start_row, start_col]:
            continue
        stack = [(int(start_row), int(start_col))]
        pixels = []
        visited[start_row, start_col] = True
        while stack:
            row, col = stack.pop()
            pixels.append((row, col))
            for dr in (-1, 0, 1):
                for dc in (-1, 0, 1):
                    if dr == 0 and dc == 0:
                        continue
                    nr, nc = row + dr, col + dc
                    if 0 <= nr < h and 0 <= nc < w and not visited[nr, nc] and detection_map[nr, nc] > 0.5:
                        visited[nr, nc] = True
                        stack.append((nr, nc))
        values = np.array([signal_map[row, col] for row, col in pixels])
        peak_index = int(np.argmax(values))
        peak_row, peak_col = pixels[peak_index]
        clusters.append(
            {
                "peak_pixel_row": int(peak_row),
                "peak_pixel_col": int(peak_col),
                "peak_power_dbm": float(values[peak_index]),
                "mean_power_dbm": float(values.mean()),
                "size": len(pixels),
            }
        )
    clusters.sort(key=lambda item: item["peak_power_dbm"], reverse=True)
    return clusters


def _render_cfar_png(
    reconstructed_iss: np.ndarray,
    outdoor_mask: np.ndarray,
    building_map: np.ndarray,
    cfar_result: dict[str, Any],
    mode_label: str = "Sim",
) -> bytes:
    fig, axes = plt.subplots(2, 2, figsize=(12, 10))
    detection_map = cfar_result["detection_map"]
    threshold_map = cfar_result["threshold_map"]
    clusters = cfar_result["clusters"]

    im0 = axes[0, 0].imshow(reconstructed_iss, cmap="jet", origin="upper", vmin=-140, vmax=-40)
    axes[0, 0].set_title("Reconstructed ISS")
    plt.colorbar(im0, ax=axes[0, 0], label="Power (dBm)", shrink=0.8)
    for cluster in clusters:
        axes[0, 0].scatter(cluster["peak_pixel_col"], cluster["peak_pixel_row"], marker="x", s=90, c="white")

    axes[0, 1].imshow(building_map, cmap="gray", origin="upper", alpha=0.5)
    axes[0, 1].imshow(np.ma.masked_where(detection_map < 0.5, detection_map), cmap="Reds", origin="upper", alpha=0.8)
    axes[0, 1].set_title("CFAR Detection Map")
    for cluster in clusters:
        axes[0, 1].scatter(cluster["peak_pixel_col"], cluster["peak_pixel_row"], marker="^", s=120, c="red", edgecolors="black")

    threshold_display = np.where(np.isnan(threshold_map), ISS_MIN_DBM, threshold_map)
    threshold_display = np.where(outdoor_mask > 0.5, threshold_display, ISS_MIN_DBM)
    im2 = axes[1, 0].imshow(threshold_display, cmap="viridis", origin="upper")
    axes[1, 0].set_title("CFAR Threshold Map")
    plt.colorbar(im2, ax=axes[1, 0], label="Threshold (dBm)", shrink=0.8)

    axes[1, 1].axis("off")
    summary = [
        "OS-CFAR Detection Summary",
        f"Raw detections: {len(cfar_result['detections'])}",
        f"Clustered jammers: {len(clusters)}",
    ]
    for index, cluster in enumerate(clusters[:5], start=1):
        summary.append(
            f"#{index}: pixel ({cluster['peak_pixel_col']}, {cluster['peak_pixel_row']}) "
            f"{cluster['peak_power_dbm']:+.1f} dBm"
        )
    axes[1, 1].text(0.5, 0.5, "\n".join(summary), ha="center", va="center", family="monospace")

    for ax in axes.flat[:3]:
        ax.axis("off")
    fig.suptitle(f"ISS_UNET - {mode_label}")
    fig.tight_layout()
    return _figure_to_png(fig)


def reconstruct_iss_unet(
    scene: str,
    sparse_ratio: float = 0.2,
    cfar: ISSUNetCFARParams | None = None,
    seed: int = 41,
    device: str = "cuda",
    mode: str = "sim",
    gps_csv: Path | str | bytes | None = None,
    noise_csv: Path | str | bytes | None = None,
    apply_building_mask: bool = True,
) -> dict[str, Any]:
    mode = mode.strip().lower()
    if mode not in ISS_UNET_MODE_LABELS:
        raise ValueError("mode must be one of: sim, gps, gps_n")
    mode_label = ISS_UNET_MODE_LABELS[mode]
    sparse_ratio = _normalize_sparse_ratio(sparse_ratio)
    dataset = resolve_scene_dataset(scene)
    if not dataset.available:
        raise FileNotFoundError(json.dumps({"scene": dataset.scene, "missing_files": dataset.missing_files}))
    if not MODEL_ARTIFACT_PATH.exists():
        logger.error(f"ISS_UNET model artifact not found at: {MODEL_ARTIFACT_PATH}")
        raise FileNotFoundError("ISS_UNET model artifact not found on the server. Please check the backend configuration.")

    arrays = load_scene_arrays(dataset)
    sparse_values_dbm = None
    real_metrics: dict[str, Any] = {
        "mode": mode,
        "route_points": 0,
        "used_samples": 0,
        "aligned_noise": 0,
        "skipped_noise": 0,
        "sample_used": False,
    }
    if mode == "sim":
        inputs, sparse_mask, outdoor_mask = build_model_input(arrays, sparse_ratio=sparse_ratio, seed=seed)
        real_metrics["used_samples"] = int(sparse_mask.sum())
    else:
        from app.iss_real import create_route_sparse_sample, parse_gps_csv, parse_noise_csv

        gps_points = parse_gps_csv(gps_csv) if gps_csv is not None else None
        noise_points = parse_noise_csv(noise_csv) if noise_csv is not None else None
        route_sample = create_route_sparse_sample(
            arrays,
            dataset,
            mode=mode,
            gps_points=gps_points,
            noise_points=noise_points,
            apply_building_mask=apply_building_mask,
        )
        inputs = route_sample.inputs
        sparse_mask = route_sample.sparse_mask
        outdoor_mask = route_sample.outdoor_mask
        sparse_values_dbm = route_sample.iss_sparse_dbm
        real_metrics = route_sample.metrics

    import torch

    model, torch_device = _load_model(device)
    tensor = torch.from_numpy(inputs).float().unsqueeze(0).to(torch_device)
    with torch.no_grad():
        output = model(tensor)
    reconstructed_norm = output[0, 0].detach().cpu().numpy()
    reconstructed_iss = _clip_radio_map(_denormalize_iss(reconstructed_norm))

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    if mode == "sim":
        stem = f"iss_unet_{dataset.scene.lower()}_{sparse_ratio_label(sparse_ratio)}"
    else:
        stem = f"iss_unet_{dataset.scene.lower()}_{mode}"
    reconstructed_path = OUTPUT_DIR / f"{stem}_reconstructed.png"
    comparison_path = OUTPUT_DIR / f"{stem}_comparison.png"
    cfar_path = OUTPUT_DIR / f"{stem}_cfar.png"
    npy_path = OUTPUT_DIR / f"{stem}_reconstructed.npy"

    reconstructed_png = _render_reconstructed_png(reconstructed_iss, mode_label=mode_label)
    if sparse_values_dbm is None and mode_label == "Sim":
        comparison_png = _render_comparison_png(arrays, reconstructed_iss, sparse_mask, outdoor_mask, sparse_ratio)
    else:
        comparison_png = _render_comparison_png(
            arrays,
            reconstructed_iss,
            sparse_mask,
            outdoor_mask,
            sparse_ratio,
            mode_label=mode_label,
            sparse_values_dbm=sparse_values_dbm,
        )
    reconstructed_path.write_bytes(reconstructed_png)
    comparison_path.write_bytes(comparison_png)
    np.save(npy_path, reconstructed_iss.astype(np.float32))

    cfar_result = None
    if cfar is None:
        cfar = ISSUNetCFARParams(enabled=True)
    if cfar.enabled:
        cfar_result = _cfar_detect(reconstructed_iss, outdoor_mask, cfar)
        cfar_path.write_bytes(_render_cfar_png(reconstructed_iss, outdoor_mask, arrays["building"], cfar_result, mode_label=mode_label))

    outdoor_pixels = outdoor_mask > 0.5
    error = np.abs(reconstructed_iss - arrays["iss"])
    metrics = {
        "mae_outdoor_db": float(error[outdoor_pixels].mean()) if np.any(outdoor_pixels) else None,
        "rmse_outdoor_db": float(np.sqrt((error[outdoor_pixels] ** 2).mean())) if np.any(outdoor_pixels) else None,
        "sparse_samples": int(sparse_mask.sum()),
        "outdoor_pixels": int(outdoor_pixels.sum()),
        "output_shape": list(reconstructed_iss.shape),
        **real_metrics,
    }
    return {
        "scene": dataset.scene,
        "mode": mode,
        "mode_label": mode_label,
        "sparse_ratio": sparse_ratio,
        "metrics": metrics,
        "options": {
            "apply_building_mask": apply_building_mask,
        },
        "images": {
            "reconstructed": result_image_url(reconstructed_path.name),
            "comparison": result_image_url(comparison_path.name),
            "cfar": result_image_url(cfar_path.name) if cfar.enabled else None,
        },
        "files": {
            "reconstructed_png": str(reconstructed_path),
            "comparison_png": str(comparison_path),
            "cfar_png": str(cfar_path) if cfar.enabled else None,
            "reconstructed_npy": str(npy_path),
        },
        "cfar": {
            "detections": len(cfar_result["detections"]) if cfar_result else 0,
            "clusters": cfar_result["clusters"] if cfar_result else [],
        },
    }
