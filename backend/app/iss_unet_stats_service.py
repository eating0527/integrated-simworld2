from __future__ import annotations

import io
import math
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.font_manager as font_manager
import matplotlib.pyplot as plt
from matplotlib.transforms import Bbox
import numpy as np

from app.iss_unet_service import (
    ISSUNetArtifacts,
    ISSUNetCFARParams,
    OUTPUT_DIR,
    _build_iss_unet_artifacts,
    output_dir_for_scene,
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
            "meaning": "干擾採樣與座標資料的時間同步品質",
        },
        {
            "variable": "有效量測率",
            "value": _format_percent(_safe_divide(aligned_noise - out_of_bounds - indoor_filtered, aligned_noise)),
            "meaning": "干擾採樣成功落在虛擬場景有效區域的比例",
        },
        {
            "variable": "相異採樣點率",
            "value": _format_percent(_safe_divide(used_samples, valid_projected_points)),
            "meaning": "排除重複採樣點後，剩餘相異採樣點的比例",
        },
        {
            "variable": "採樣點地圖覆蓋率",
            "value": _format_percent(_safe_divide(used_samples, outdoor_pixels)),
            "meaning": "干擾採樣佔 512*512 室外地圖的比例",
        },
        {
            "variable": "干擾熱區強度",
            "value": _format_db(noise_p95, "dBm"),
            "meaning": "干擾熱區訊號強度，取 95 百分位數",
        },
        {
            "variable": "虛實空間相關度",
            "value": _format_corr(sim_real_corr),
            "meaning": "重建干擾地圖 vs 真實量測值的空間趨勢一致程度，越接近 1 越好",
        },
        {
            "variable": "虛實平均誤差",
            "value": _format_db(sim_real_mae, "dB"),
            "meaning": "模擬干擾地圖 vs 真實量測值的 MAE",
        },
        {
            "variable": "重建樣本平均誤差",
            "value": _format_db(sample_point_mae, "dB"),
            "meaning": "重建干擾地圖 vs 真實量測值的 MAE",
        },
        {
            "variable": "重建樣本偏差",
            "value": _format_db(sample_point_bias, "dB"),
            "meaning": "重建結果是否系統性高估或低估量測值",
        },
        {
            "variable": "CFAR 熱點定位誤差",
            "value": _format_px(hotspot_error),
            "meaning": "重建干擾源 vs 真實干擾源的定位誤差",
        },
    ]


def _pick_font(candidates: tuple[str, ...], fallback: str) -> str:
    available = {font.name for font in font_manager.fontManager.ttflist}
    return next((name for name in candidates if name in available), fallback)


def _configure_statistics_fonts() -> dict[str, font_manager.FontProperties]:
    cjk_font = _pick_font(
        ("DFKai-SB", "BiauKai", "KaiTi", "Microsoft JhengHei", "Noto Sans CJK TC", "Arial Unicode MS"),
        "DejaVu Sans",
    )
    latin_font = _pick_font(("Times New Roman", "Times", "DejaVu Serif"), "DejaVu Serif")
    plt.rcParams["font.family"] = [latin_font, cjk_font]
    plt.rcParams["axes.unicode_minus"] = False
    return {
        "body_cjk": font_manager.FontProperties(family=cjk_font, size=10),
        "body_latin": font_manager.FontProperties(family=latin_font, size=10),
        "header": font_manager.FontProperties(family=cjk_font, size=10, weight="bold"),
        "caption": font_manager.FontProperties(family=cjk_font, size=13),
    }


def _statistics_column_labels() -> list[str]:
    return ["統計指標", "數值", "說明"]


def _statistics_table_title(scene: str) -> str:
    return f"{scene.upper()} 統計資料"


def render_statistics_table_png(rows: list[dict[str, str]], title: str = "統計資料") -> bytes:
    fonts = _configure_statistics_fonts()
    fig, ax = plt.subplots(figsize=(12, 5.8), facecolor="white")
    ax.set_facecolor("white")
    ax.axis("off")
    table = ax.table(
        cellText=[[row["variable"], row["value"], row["meaning"]] for row in rows],
        colLabels=_statistics_column_labels(),
        colWidths=[0.24, 0.18, 0.58],
        cellLoc="left",
        loc="center",
    )
    table.auto_set_font_size(False)
    table.scale(1, 1.55)
    last_row_index = len(rows)
    for (row_index, col_index), cell in table.get_celld().items():
        cell.set_facecolor("white")
        cell.set_edgecolor("#1f1f1f")
        cell.PAD = 0.08
        if row_index == 0:
            cell.visible_edges = "TB"
            cell.set_linewidth(1.1)
            cell.set_text_props(color="#111111", fontproperties=fonts["header"])
        elif row_index == last_row_index:
            cell.visible_edges = "B"
            cell.set_linewidth(1.1)
            font_key = "body_latin" if col_index == 1 else "body_cjk"
            cell.set_text_props(color="#111111", fontproperties=fonts[font_key])
        else:
            cell.visible_edges = "B"
            cell.set_linewidth(0.55)
            font_key = "body_latin" if col_index == 1 else "body_cjk"
            cell.set_text_props(color="#111111", fontproperties=fonts[font_key])
    fig.subplots_adjust(left=0.035, right=0.965, top=0.965, bottom=0.14)
    fig.canvas.draw()
    table_bbox = table.get_window_extent(fig.canvas.get_renderer()).transformed(fig.transFigure.inverted())
    title_y = min(0.965, table_bbox.y1 + 0.06)
    title_text = fig.text(0.5, title_y, title, ha="center", va="bottom", fontproperties=fonts["caption"])
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    output_bbox = Bbox.union(
        [
            table.get_window_extent(renderer).transformed(fig.dpi_scale_trans.inverted()),
            title_text.get_window_extent(renderer).transformed(fig.dpi_scale_trans.inverted()),
        ]
    ).padded(0.15)
    buffer = io.BytesIO()
    fig.savefig(buffer, format="png", dpi=160, bbox_inches=output_bbox)
    plt.close(fig)
    return buffer.getvalue()


def save_statistics_table_png(scene: str, rows: list[dict[str, str]], grid_res: int = 128) -> Path:
    output_dir = output_dir_for_scene(scene)
    output_dir.mkdir(parents=True, exist_ok=True)
    resolution_label = "" if grid_res == 128 else f"_res{grid_res}"
    path = output_dir / f"iss_unet_{scene.lower()}{resolution_label}_gps_n_statistics.png"
    path.write_bytes(render_statistics_table_png(rows, title=_statistics_table_title(scene)))
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
    scene_dir: Path | None = None,
    devices: list[Any] | None = None,
    scene_xml_path: Path | str | None = None,
    pixel_size_m: float = 4.0,
    filter_noise: bool = True,
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
        scene_dir=scene_dir,
        devices=devices,
        scene_xml_path=scene_xml_path,
        pixel_size_m=pixel_size_m,
        filter_noise=filter_noise,
    )
    rows = build_gpsn_statistics_rows(artifacts)
    image_path = save_statistics_table_png(artifacts.dataset.scene, rows, grid_res=artifacts.dataset.grid_res)
    return {
        "scene": artifacts.dataset.scene,
        "mode": "gps_n",
        "statistics": {"rows": rows},
        "images": {"statistics": result_image_url(image_path.name, artifacts.dataset.scene)},
        "files": {"statistics_png": str(image_path)},
    }
