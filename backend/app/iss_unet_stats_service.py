from __future__ import annotations

import io
import math
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.font_manager as font_manager
import matplotlib.pyplot as plt
import numpy as np

from app.iss_unet_service import (
    ISSUNetArtifacts,
    ISSUNetCFARParams,
    OUTPUT_DIR,
    _build_iss_unet_artifacts,
    result_image_url,
)


def _safe_divide(numerator: float, denominator: float) -> float | None:
    if denominator == 0:
        return None
    value = numerator / denominator
    return float(value) if np.isfinite(value) else None


def _format_percent(value: float | None) -> str:
    return "N/A" if value is None else f"{value * 100:.2f}%"


def _format_db(value: float | None, unit: str) -> str:
    return "N/A" if value is None else f"{value:.2f} {unit}"


def _format_corr(value: float | None) -> str:
    return "N/A" if value is None else f"{value:.3f}"


def _format_px(value: float | None) -> str:
    return "N/A" if value is None else f"{value:.2f} px"


def _pearson_corr(a: np.ndarray, b: np.ndarray) -> float | None:
    if a.size < 2 or b.size < 2:
        return None
    if float(np.std(a)) == 0.0 or float(np.std(b)) == 0.0:
        return None
    corr = float(np.corrcoef(a.astype(np.float64), b.astype(np.float64))[0, 1])
    return corr if np.isfinite(corr) else None


def _cfar_hotspot_error_px(artifacts: ISSUNetArtifacts) -> float | None:
    clusters = (artifacts.cfar_result or {}).get("clusters", [])
    if not clusters or artifacts.sparse_values_dbm is None:
        return None

    sample_mask = artifacts.sparse_mask > 0.5
    measured_values = artifacts.sparse_values_dbm[sample_mask]
    if measured_values.size == 0:
        return None

    threshold = float(np.percentile(measured_values, 90))
    hot_points = np.argwhere(sample_mask & (artifacts.sparse_values_dbm >= threshold))
    if hot_points.size == 0:
        hot_points = np.argwhere(sample_mask)
    if hot_points.size == 0:
        return None

    best = math.inf
    for cluster in clusters:
        peak = np.array([float(cluster["peak_pixel_row"]), float(cluster["peak_pixel_col"])])
        distances = np.sqrt(np.sum((hot_points.astype(np.float64) - peak) ** 2, axis=1))
        best = min(best, float(distances.min()))
    return best if math.isfinite(best) else None


def build_gpsn_statistics_rows(artifacts: ISSUNetArtifacts) -> list[dict[str, str]]:
    if artifacts.mode != "gps_n":
        raise ValueError("GPS_N statistics require mode='gps_n'")
    if artifacts.sparse_values_dbm is None:
        raise ValueError("GPS_N statistics require sparse measured values")

    metrics = artifacts.real_metrics
    aligned_noise = float(metrics.get("aligned_noise") or 0)
    skipped_noise = float(metrics.get("skipped_noise") or 0)
    out_of_bounds = float(metrics.get("out_of_bounds") or 0)
    indoor_filtered = float(metrics.get("indoor_filtered") or 0)
    valid_projected_points = float(metrics.get("valid_projected_points") or 0)
    used_samples = float(metrics.get("used_samples") or artifacts.sparse_mask.sum())
    outdoor_pixels = float((artifacts.outdoor_mask > 0.5).sum())

    sample_mask = artifacts.sparse_mask > 0.5
    measured_values = artifacts.sparse_values_dbm[sample_mask].astype(np.float32)
    sim_values = artifacts.arrays["iss"][sample_mask].astype(np.float32)
    reconstructed_values = artifacts.reconstructed_iss[sample_mask].astype(np.float32)
    valid_noise_values = np.array(metrics.get("valid_projected_noise_dbm") or [], dtype=np.float32)
    if valid_noise_values.size == 0:
        valid_noise_values = measured_values

    sim_real_mae = float(np.mean(np.abs(sim_values - measured_values))) if measured_values.size else None
    sim_real_corr = _pearson_corr(sim_values, measured_values)
    sample_point_mae = float(np.mean(np.abs(reconstructed_values - measured_values))) if measured_values.size else None
    sample_point_bias = float(np.mean(reconstructed_values - measured_values)) if measured_values.size else None
    noise_p95 = float(np.percentile(valid_noise_values, 95)) if valid_noise_values.size else None
    hotspot_error = _cfar_hotspot_error_px(artifacts)

    return [
        {
            "variable": "GPS/Noise 時間對齊率",
            "value": _format_percent(_safe_divide(aligned_noise, aligned_noise + skipped_noise)),
            "meaning": "noise.csv 與 gps.csv 的時間同步品質",
        },
        {
            "variable": "有效量測率",
            "value": _format_percent(_safe_divide(aligned_noise - out_of_bounds - indoor_filtered, aligned_noise)),
            "meaning": "真實量測成功落在虛擬場景有效區域的比例",
        },
        {
            "variable": "唯一採樣格點比例",
            "value": _format_percent(_safe_divide(used_samples, valid_projected_points)),
            "meaning": "有效投影點轉成地圖格點後，有多少不是重複格點",
        },
        {
            "variable": "採樣點地圖覆蓋率",
            "value": _format_percent(_safe_divide(used_samples, outdoor_pixels)),
            "meaning": "採樣點覆蓋整張室外地圖的比例",
        },
        {
            "variable": "實測干擾 95 百分位",
            "value": _format_db(noise_p95, "dBm"),
            "meaning": "真實干擾強度熱點的代表值",
        },
        {
            "variable": "虛實樣本平均誤差",
            "value": _format_db(sim_real_mae, "dB"),
            "meaning": "虛擬 Sionna 干擾圖與真實量測在同一位置的功率差",
        },
        {
            "variable": "虛實空間趨勢相關",
            "value": _format_corr(sim_real_corr),
            "meaning": "虛擬圖與真實量測的空間趨勢一致程度",
        },
        {
            "variable": "重建樣本平均誤差",
            "value": _format_db(sample_point_mae, "dB"),
            "meaning": "重建地圖是否貼近真實量測點",
        },
        {
            "variable": "重建樣本偏差",
            "value": _format_db(sample_point_bias, "dB"),
            "meaning": "重建結果是否系統性高估或低估",
        },
        {
            "variable": "CFAR 熱點定位誤差",
            "value": _format_px(hotspot_error),
            "meaning": "偵測出的干擾熱點是否貼近實測熱點",
        },
    ]


def _configure_cjk_font() -> None:
    candidates = ("Microsoft JhengHei", "Noto Sans CJK TC", "Noto Sans CJK SC", "SimHei", "Arial Unicode MS")
    available = {font.name for font in font_manager.fontManager.ttflist}
    for name in candidates:
        if name in available:
            plt.rcParams["font.family"] = name
            break
    plt.rcParams["axes.unicode_minus"] = False


def render_statistics_table_png(rows: list[dict[str, str]]) -> bytes:
    _configure_cjk_font()
    fig, ax = plt.subplots(figsize=(12, 5.8))
    ax.axis("off")
    table = ax.table(
        cellText=[[row["variable"], row["value"], row["meaning"]] for row in rows],
        colLabels=["變數", "數值", "代表意義"],
        colWidths=[0.24, 0.18, 0.58],
        cellLoc="left",
        loc="center",
    )
    table.auto_set_font_size(False)
    table.set_fontsize(10)
    table.scale(1, 1.55)
    for (row_index, _col_index), cell in table.get_celld().items():
        cell.set_edgecolor("#33515c")
        if row_index == 0:
            cell.set_facecolor("#d8f7ff")
            cell.set_text_props(weight="bold", color="#0b1f28")
        else:
            cell.set_facecolor("#f8fbfc" if row_index % 2 else "#eef6f8")
    fig.suptitle("ISS_UNET GPS_N 統計資料", fontsize=16, fontweight="bold")
    fig.tight_layout()
    buffer = io.BytesIO()
    fig.savefig(buffer, format="png", dpi=160, bbox_inches="tight")
    plt.close(fig)
    return buffer.getvalue()


def save_statistics_table_png(scene: str, rows: list[dict[str, str]]) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTPUT_DIR / f"iss_unet_{scene.lower()}_gps_n_statistics.png"
    path.write_bytes(render_statistics_table_png(rows))
    return path


def generate_gpsn_statistics(
    *,
    scene: str,
    cfar: ISSUNetCFARParams | None = None,
    seed: int = 41,
    device: str = "cuda",
    mode: str = "gps_n",
    gps_csv: Path | str | bytes | None = None,
    noise_csv: Path | str | bytes | None = None,
    apply_building_mask: bool = True,
    focus_sampling_points: bool = True,
    scene_dir: Path | None = None,
    devices: list[Any] | None = None,
    scene_xml_path: Path | str | None = None,
) -> dict[str, Any]:
    if mode != "gps_n":
        raise ValueError("statistics generation only supports gps_n mode")
    artifacts = _build_iss_unet_artifacts(
        scene=scene,
        sparse_ratio=0.2,
        cfar=cfar or ISSUNetCFARParams(enabled=True),
        seed=seed,
        device=device,
        mode="gps_n",
        gps_csv=gps_csv,
        noise_csv=noise_csv,
        apply_building_mask=apply_building_mask,
        focus_sampling_points=focus_sampling_points,
        scene_dir=scene_dir,
        devices=devices,
        scene_xml_path=scene_xml_path,
    )
    rows = build_gpsn_statistics_rows(artifacts)
    image_path = save_statistics_table_png(artifacts.dataset.scene, rows)
    return {
        "scene": artifacts.dataset.scene,
        "mode": "gps_n",
        "statistics": {"rows": rows},
        "images": {"statistics": result_image_url(image_path.name)},
        "files": {"statistics_png": str(image_path)},
    }
