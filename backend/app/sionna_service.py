"""
sionna_service.py — 無線通道模擬服務（不依賴資料庫）

提供：
  - SINR Map（訊號干擾雜訊比地圖）
  - CFR Plot（通道頻率響應）
  - Delay-Doppler Plot（延遲多普勒圖）
  - Channel Response Plot（通道響應圖，H_des / H_jam / H_all）

TX/RX 位置均透過函式參數傳入，預設使用 NYCU 場景。
"""
import logging
import os
import matplotlib
matplotlib.use("Agg")   # headless backend（無 display）
import matplotlib.pyplot as plt
import numpy as np
from pathlib import Path
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)


class SionnaLLVMError(ImportError):
    """Raised when Sionna RT cannot initialize the Dr.Jit LLVM backend."""


def _is_llvm_error(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return any(
        token in msg
        for token in (
            "llvm-c.dll",
            "drjit_libllvm_path",
            "llvm backend",
            "llvm shared library",
            "jitc_llvm_init",
            "jit_init_thread_state",
        )
    )


def _format_llvm_error(exc: BaseException) -> str:
    return (
        "Sionna RT 需要 LLVM，但找不到 LLVM-C.dll。"
        "請安裝 LLVM，或設定 DRJIT_LIBLLVM_PATH 指向完整 DLL 路徑，"
        r"例如 C:\Program Files\LLVM\bin\LLVM-C.dll。"
        f"原始錯誤：{exc}"
    )

# ── 路徑設定 ────────────────────────────────────────────────────────────────
_HERE = Path(__file__).parent
SCENE_DIR   = _HERE / "static" / "scenes"
OUTPUT_DIR  = _HERE / "static" / "images"
NYCU_XML    = SCENE_DIR / "NYCU" / "NYCU.xml"

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

SINR_MAP_PATH     = str(OUTPUT_DIR / "sinr_map.png")
CFR_PLOT_PATH     = str(OUTPUT_DIR / "cfr_plot.png")
DOPPLER_PLOT_PATH = str(OUTPUT_DIR / "doppler_plot.png")
CHANNEL_RESP_PATH = str(OUTPUT_DIR / "channel_response.png")

# ── 預設 TX / RX 位置（NYCU 場景座標系）──────────────────────────────────────
DEFAULT_TX_LIST = [
    # (name, [x, y, z], [ry, rp, rr], role, power_dbm)
    ("desired_tx", [-30, 50, 20], [0.0, 0.0, 0.0], "desired", 23.0),
]
DEFAULT_JAM_LIST = [
    ("jammer_tx", [30, -50, 20], [0.0, 0.0, 0.0], "jammer", 23.0),
]
DEFAULT_RX = ("rx", [-170, 10, 200])


# ── 工具函式 ─────────────────────────────────────────────────────────────────
def _clean(path: str):
    if os.path.exists(path):
        os.remove(path)


def _verify(path: str) -> bool:
    ok = os.path.isfile(path) and os.path.getsize(path) > 0
    if ok:
        logger.info(f"✅ 圖檔生成成功: {path} ({os.path.getsize(path)} bytes)")
    else:
        logger.error(f"❌ 圖檔生成失敗: {path}")
    return ok


def _setup_torch():
    try:
        import torch
        if torch.cuda.is_available():
            device = torch.device("cuda")
            logger.info("PyTorch CUDA 已啟用: %s", torch.cuda.get_device_name(0))
        else:
            device = torch.device("cpu")
            logger.info("PyTorch 未找到 CUDA GPU，使用 CPU（速度較慢）")
        return device
    except ImportError:
        logger.warning("PyTorch 未安裝，Sionna 2.x PHY/SYS 功能可能無法使用")
        return None


def _load_sionna():
    """延遲載入 sionna，確保執行時才報錯（import 階段不崩潰）"""
    import os
    # Auto-discover LLVM-C.dll on Windows if env var not set
    if not os.environ.get("DRJIT_LIBLLVM_PATH"):
        _candidates = [
            r"C:\Program Files\LLVM\bin\LLVM-C.dll",
            r"C:\Program Files (x86)\LLVM\bin\LLVM-C.dll",
        ]
        for _c in _candidates:
            if os.path.isfile(_c):
                os.environ["DRJIT_LIBLLVM_PATH"] = _c
                logger.info(f"Auto-set DRJIT_LIBLLVM_PATH={_c}")
                break
    try:
        # 必須在 sionna.rt import 之前設定 variant。
        # sionna/rt/__init__.py 的邏輯：if mi.variant() is None → try cuda first。
        # 預先設定 llvm_ad_mono_polarized 可避免它選到 CUDA（無 OptiX 會炸）。
        import mitsuba as mi
        if mi.variant() is None:
            mi.set_variant("llvm_ad_mono_polarized")

        from sionna.rt import (
            load_scene,
            Transmitter as SionnaTX,
            Receiver as SionnaRX,
            PlanarArray,
            PathSolver,
            subcarrier_frequencies,
            RadioMapSolver,
        )
        return load_scene, SionnaTX, SionnaRX, PlanarArray, PathSolver, subcarrier_frequencies, RadioMapSolver
    except ImportError as e:
        if _is_llvm_error(e):
            raise SionnaLLVMError(_format_llvm_error(e)) from e
        raise ImportError(
            f"sionna 套件未安裝: {e}\n"
            "請在 backend/.venv 中執行：pip install sionna sionna-rt"
        ) from e


def _build_scene(load_scene, SionnaTX, SionnaRX, PlanarArray,
                 tx_list, rx_config, scene_xml: str):
    """建立 Sionna 場景並加入 TX/RX"""
    array_cfg = dict(
        num_rows=1, num_cols=1,
        vertical_spacing=0.5, horizontal_spacing=0.5,
        pattern="iso", polarization="V",
    )
    scene = load_scene(scene_xml)
    scene.tx_array = PlanarArray(**array_cfg)
    scene.rx_array = PlanarArray(**array_cfg)

    # 清空現有設備
    for name in list(scene.transmitters.keys()) + list(scene.receivers.keys()):
        scene.remove(name)

    # 加入 TX
    for name, pos, ori, role, power_dbm in tx_list:
        tx = SionnaTX(name=name, position=pos, orientation=ori, power_dbm=power_dbm)
        tx.role = role
        scene.add(tx)

    # 加入 RX
    rx_name, rx_pos = rx_config
    scene.add(SionnaRX(name=rx_name, position=rx_pos))

    return scene


# ── SINR Map ─────────────────────────────────────────────────────────────────
async def generate_sinr_map(
    output_path: str = SINR_MAP_PATH,
    tx_list: Optional[List[Tuple]] = None,
    rx_config: Optional[Tuple] = None,
    sinr_vmin: float = -40.0,
    sinr_vmax: float = 0.0,
    cell_size: float = 1.0,
    samples_per_tx: int = 10 ** 7,
) -> bool:
    """
    生成 SINR Map。

    tx_list: [(name, [x,y,z], [ry,rp,rr], role('desired'|'jammer'), power_dbm), ...]
    rx_config: (name, [x,y,z])
    """
    logger.info("▶ 開始生成 SINR Map...")
    _clean(output_path)

    try:
        load_scene, SionnaTX, SionnaRX, PlanarArray, PathSolver, subcarrier_frequencies, RadioMapSolver = _load_sionna()
        _setup_torch()

        if tx_list is None:
            tx_list = DEFAULT_TX_LIST + DEFAULT_JAM_LIST
        if rx_config is None:
            rx_config = DEFAULT_RX

        scene_xml = str(NYCU_XML)
        logger.info(f"使用場景: {scene_xml}")

        scene = _build_scene(load_scene, SionnaTX, SionnaRX, PlanarArray,
                             tx_list, rx_config, scene_xml)

        # 記錄 TX 的 role 與 power（依 tx_list 順序對應 RadioMap 的 TX 索引）
        tx_meta = [(role, power_dbm) for _, _, _, role, power_dbm in tx_list]
        idx_des = [i for i, (role, _) in enumerate(tx_meta) if role == "desired"]
        idx_jam = [i for i, (role, _) in enumerate(tx_meta) if role == "jammer"]

        if not tx_meta:
            logger.error("沒有可用的發射器，無法生成 SINR Map")
            return False

        # 計算 Radio Map
        logger.info("計算無線電地圖...")
        rm_solver = RadioMapSolver()
        rm = rm_solver(scene, max_depth=10,
                       cell_size=(cell_size, cell_size),
                       samples_per_tx=samples_per_tx)

        # path_gain: [num_tx, H, W]（線性，無單位）
        pg = rm.path_gain.numpy()

        # cell_centers: [H, W, 3] → 取 X/Y 座標
        cc = rm.cell_centers.numpy()
        X = cc[:, :, 0]
        Y = cc[:, :, 1]

        # ── 計算 SINR ────────────────────────────────────────────────────
        N0_dbm = -100.0  # 噪音底線 dBm
        N0_w   = 10 ** ((N0_dbm - 30) / 10)

        def pg_to_rss_w(i):
            """path_gain → RSS (Watts)"""
            power_w = 10 ** ((tx_meta[i][1] - 30) / 10)
            return pg[i] * power_w

        eps = 1e-30  # 避免 log(0)

        if idx_des and idx_jam:
            P_des = sum(pg_to_rss_w(i) for i in idx_des)
            P_jam = sum(pg_to_rss_w(i) for i in idx_jam)
            sinr_db = 10 * np.log10(P_des / (P_jam + N0_w) + eps)
        elif idx_des:
            P_des   = sum(pg_to_rss_w(i) for i in idx_des)
            sinr_db = 10 * np.log10(P_des / N0_w + eps)
        else:
            P_all   = sum(pg_to_rss_w(i) for i in range(len(tx_meta)))
            sinr_db = 10 * np.log10(P_all / N0_w + eps)

        sinr_db = np.clip(sinr_db, sinr_vmin - 5, sinr_vmax + 5)

        # ── 繪圖 ─────────────────────────────────────────────────────────
        fig, ax = plt.subplots(figsize=(10, 8))
        c = ax.pcolormesh(X, Y, sinr_db,
                          cmap="RdYlGn", vmin=sinr_vmin, vmax=sinr_vmax,
                          shading="auto")
        plt.colorbar(c, ax=ax, label="SINR (dB)")
        ax.set_title("SINR Map (NYCU Scene)")
        ax.set_xlabel("X (m)")
        ax.set_ylabel("Y (m)")
        plt.tight_layout()

        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        plt.savefig(output_path, dpi=150, bbox_inches="tight")
        plt.close(fig)
        return _verify(output_path)

    except SionnaLLVMError:
        plt.close("all")
        raise
    except Exception as e:
        logger.exception(f"生成 SINR Map 時出錯: {e}")
        plt.close("all")
        raise  # 讓 endpoint 能取得實際錯誤訊息


# ─────────────────────────────────────────────────────────────────────────────
# 共用：用 paths.cir() 計算通道矩陣（Sionna 1.2+ API）
#
#   paths.cir(sampling_frequency, num_time_steps, normalize_delays, out_type)
#   → (a, tau)
#       a:   [num_rx, rx_ant, num_tx, tx_ant, num_paths, T]  複數 numpy
#       tau: [num_rx, num_tx, num_paths]  秒
# ─────────────────────────────────────────────────────────────────────────────

def _solver_and_cir(scene, PathSolver, n_time=1, samp_freq=30e3,
                    normalize_delays=True, max_depth=5, seed=41,
                    out_type="numpy"):
    """建立 PathSolver，取 CIR，回傳 (a, tau, paths)"""
    for name in scene.transmitters:
        scene.get(name).velocity = [30, 0, 0]

    ps = PathSolver()(scene,
                      max_depth=max_depth, los=True,
                      specular_reflection=True,
                      diffuse_reflection=False,
                      refraction=False,
                      synthetic_array=False, seed=seed)

    a, tau = ps.cir(sampling_frequency=samp_freq,
                    num_time_steps=n_time,
                    normalize_delays=normalize_delays,
                    out_type=out_type)
    return a, tau


def _dbm2w(dbm): return 10 ** (dbm / 10) / 1e3


def _compute_H_f(a, tau, tx_i, freqs_hz):
    """單一 TX 的 H(f) = Σ_p a_p · exp(−j2πf·τ_p)  [num_paths] → [N_F]"""
    a_p = a[0, 0, tx_i, 0, :, 0]     # [num_paths]
    t_p = tau[0, 0, tx_i, 0, :]      # [num_paths] 秒
    return np.sum(
        a_p[:, None] * np.exp(-1j * 2 * np.pi * freqs_hz[None, :] * t_p[:, None]),
        axis=0
    )


def _build_H_td(a, tau, tx_i, tx_power_w, N_DELAY, W_delay):
    """單一 TX 的 H[delay_tap, time]，按路徑時延放置振幅"""
    a_tx = a[0, 0, tx_i, 0, :, :]    # [num_paths, N_T]
    tau_tx = tau[0, 0, tx_i, 0, :]   # [num_paths] 秒
    d_idx = np.round(tau_tx * W_delay).astype(int)
    N_T = a_tx.shape[1]
    H = np.zeros((N_DELAY, N_T), dtype=complex)
    for p in range(len(d_idx)):
        d = int(d_idx[p])
        if 0 <= d < N_DELAY:
            H[d, :] += np.sqrt(tx_power_w) * a_tx[p, :]
    return H


def _compute_H_tf(a, tau, tx_i, tx_power_w, freqs_hz):
    """單一 TX 的 H(t, f) = Σ_p a_p(t)·exp(−j2πf·τ_p)  → [N_T, N_F]"""
    a_tx = a[0, 0, tx_i, 0, :, :]    # [num_paths, N_T]
    tau_tx = tau[0, 0, tx_i, 0, :]   # [num_paths] 秒
    return np.sqrt(tx_power_w) * np.sum(
        a_tx[:, :, None] * np.exp(-1j * 2 * np.pi * freqs_hz[None, None, :] * tau_tx[:, None, None]),
        axis=0
    )


# ── CFR Plot ──────────────────────────────────────────────────────────────────
async def generate_cfr_plot(
    output_path: str = CFR_PLOT_PATH,
    tx_list: Optional[List[Tuple]] = None,
    rx_config: Optional[Tuple] = None,
    scene_xml: Optional[str] = None,
    modulation: str = "qpsk",
) -> bool:
    """生成通道頻率響應（CFR）圖 + QPSK 星座圖"""
    logger.info("▶ 開始生成 CFR Plot...")
    _clean(output_path)

    try:
        modulation = modulation.lower()
        if modulation not in {"qpsk", "16qam"}:
            raise ValueError("modulation must be 'qpsk' or '16qam'")

        load_scene, SionnaTX, SionnaRX, PlanarArray, PathSolver, subcarrier_frequencies, _ = _load_sionna()
        import torch
        from sionna.phy.channel import AWGN, ApplyOFDMChannel
        from sionna.phy.channel.utils import cir_to_ofdm_channel
        from sionna.phy.mapping import Mapper
        device = _setup_torch() or torch.device("cpu")

        if tx_list is None:
            tx_list = DEFAULT_TX_LIST + DEFAULT_JAM_LIST
        if rx_config is None:
            rx_config = DEFAULT_RX
        if scene_xml is None:
            scene_xml = str(NYCU_XML)

        scene = _build_scene(load_scene, SionnaTX, SionnaRX, PlanarArray,
                             tx_list, rx_config, scene_xml)

        tx_names = list(scene.transmitters.keys())
        all_txs  = [scene.get(n) for n in tx_names]
        idx_des  = [i for i, tx in enumerate(all_txs) if getattr(tx, "role", None) == "desired"]
        idx_jam  = [i for i, tx in enumerate(all_txs) if getattr(tx, "role", None) == "jammer"]

        N_SUB   = 76
        SCS     = 30e3
        EBN0_dB = 20.0
        freqs_hz = torch.tensor(np.array(subcarrier_frequencies(N_SUB, SCS)),
                                dtype=torch.float32, device=device)
        cir_out_type = "torch" if device.type == "cuda" else "numpy"

        a_cir, tau_cir = _solver_and_cir(scene, PathSolver,
                                         n_time=1, samp_freq=SCS,
                                         normalize_delays=True, max_depth=10,
                                         out_type=cir_out_type)

        tx_powers = [_dbm2w(scene.get(n).power_dbm) for n in tx_names]

        if torch.is_tensor(a_cir):
            a_torch = a_cir.to(device=device, dtype=torch.complex64).unsqueeze(0)
        else:
            a_torch = torch.tensor(np.expand_dims(a_cir, axis=0),
                                   dtype=torch.complex64, device=device)
        if torch.is_tensor(tau_cir):
            tau_torch = tau_cir.to(device=device, dtype=torch.float32).unsqueeze(0)
        else:
            tau_torch = torch.tensor(np.expand_dims(tau_cir, axis=0),
                                     dtype=torch.float32, device=device)
        h_freq = cir_to_ofdm_channel(freqs_hz, a_torch, tau_torch, normalize=False)
        tx_power_scale = torch.sqrt(torch.tensor(tx_powers, dtype=torch.float32, device=h_freq.device))
        tx_power_scale = tx_power_scale.to(dtype=h_freq.dtype).reshape(1, 1, 1, -1, 1, 1, 1)
        h_freq = h_freq * tx_power_scale

        h_des = h_freq.index_select(3, torch.tensor(idx_des, dtype=torch.long, device=h_freq.device))
        h_jam = h_freq.index_select(3, torch.tensor(idx_jam, dtype=torch.long, device=h_freq.device)) if idx_jam else None
        h_des_eff = h_des.sum(dim=(3, 4))
        if h_jam is not None:
            h_jam_eff = h_jam.sum(dim=(3, 4))
            jam_var = torch.square(torch.abs(h_jam)).sum(dim=(3, 4))
        else:
            h_jam_eff = torch.zeros_like(h_des_eff)
            jam_var = torch.zeros_like(h_des_eff.real)

        # QPSK + OFDM 星座圖模擬
        if modulation == "qpsk":
            mod_label = "QPSK"
            bits_per_symbol = 2
        else:
            mod_label = "16QAM"
            bits_per_symbol = 4

        mapper = Mapper("qam", bits_per_symbol)
        bits = torch.randint(0, 2, (1, 1, 1, 1, N_SUB * bits_per_symbol),
                             dtype=torch.int32, device=h_freq.device)
        x_one = mapper(bits)
        x_sig = x_one.repeat(1, len(idx_des), 1, 1, 1)
        ofdm_channel = ApplyOFDMChannel()
        y_clean = ofdm_channel(x_sig, h_des)
        p_sig = torch.square(torch.abs(y_clean)).mean()
        n0_base = torch.clamp(
            p_sig / ((10.0 ** (EBN0_dB / 10.0)) * bits_per_symbol),
            min=1e-10,
        )
        base_var = torch.ones_like(y_clean.real) * n0_base
        y_base = ofdm_channel(x_sig, h_des, base_var)
        y_tot = AWGN()(y_base, jam_var)

        mask = torch.abs(h_des_eff) > 1e-12
        zeros = torch.zeros_like(y_base)
        y_no_i = torch.where(mask, y_base / h_des_eff, zeros)
        y_with_i = torch.where(mask, y_tot / h_des_eff, zeros)

        y_no_i = y_no_i.squeeze().detach().cpu().numpy()
        y_with_i = y_with_i.squeeze().detach().cpu().numpy()
        h_main = h_des_eff.squeeze().detach().cpu().numpy()
        h_intf = h_jam_eff.squeeze().detach().cpu().numpy()

        fig, ax = plt.subplots(1, 3, figsize=(15, 4))
        ax[0].scatter(y_no_i.real,   y_no_i.imag,   s=6, alpha=0.3)
        ax[0].set(title=f"{mod_label} Without Jammer Noise",   xlabel="Real", ylabel="Imag"); ax[0].grid(True)
        ax[1].scatter(y_with_i.real, y_with_i.imag, s=6, alpha=0.3)
        ax[1].set(title=f"{mod_label} With Jammer Noise", xlabel="Real", ylabel="Imag"); ax[1].grid(True)
        ax[2].plot(np.abs(h_main), label="|H_main|")
        ax[2].plot(np.abs(h_intf), label="|H_jammer|")
        ax[2].set(title=f"CFR Magnitude ({mod_label})", xlabel="Subcarrier Index"); ax[2].legend(); ax[2].grid(True)
        plt.tight_layout()

        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        plt.savefig(output_path, dpi=150, bbox_inches="tight")
        plt.close(fig)
        return _verify(output_path)

    except SionnaLLVMError:
        plt.close("all")
        raise
    except Exception as e:
        logger.exception(f"生成 CFR Plot 時出錯: {e}")
        plt.close("all")
        return False


# ── Delay-Doppler Plot ────────────────────────────────────────────────────────
async def generate_doppler_plot(
    output_path: str = DOPPLER_PLOT_PATH,
    tx_list: Optional[List[Tuple]] = None,
    rx_config: Optional[Tuple] = None,
) -> bool:
    """生成延遲多普勒（Delay-Doppler）圖"""
    logger.info("▶ 開始生成 Delay-Doppler Plot...")
    _clean(output_path)

    try:
        load_scene, SionnaTX, SionnaRX, PlanarArray, PathSolver, subcarrier_frequencies, _ = _load_sionna()
        _setup_torch()

        if tx_list is None:
            tx_list = DEFAULT_TX_LIST + DEFAULT_JAM_LIST
        if rx_config is None:
            rx_config = DEFAULT_RX

        scene = _build_scene(load_scene, SionnaTX, SionnaRX, PlanarArray,
                             tx_list, rx_config, str(NYCU_XML))

        tx_names = list(scene.transmitters.keys())
        all_txs  = [scene.get(n) for n in tx_names]
        idx_des  = [i for i, tx in enumerate(all_txs) if getattr(tx, "role", None) == "desired"]
        idx_jam  = [i for i, tx in enumerate(all_txs) if getattr(tx, "role", None) == "jammer"]

        N_T     = 100           # OFDM 符號數（時間軸）
        SCS     = 30e3          # 子載波間距 Hz
        T_sym   = 1.0 / SCS    # OFDM 符號週期
        W_delay = 76 * SCS     # 時延軸採樣率 Hz
        N_DELAY = 60            # 時延格子數

        a_cir, tau_cir = _solver_and_cir(scene, PathSolver,
                                         n_time=N_T, samp_freq=1.0/T_sym,
                                         normalize_delays=False, max_depth=3)

        tx_powers = [_dbm2w(scene.get(n).power_dbm) for n in tx_names]

        # 每個 TX 建 H[delay, time]，再 FFT 轉 Delay-Doppler
        Hdd_list = []
        for i, _ in enumerate(tx_names):
            H_td = _build_H_td(a_cir, tau_cir, i, tx_powers[i], N_DELAY, W_delay)
            DD   = np.abs(np.fft.fftshift(np.fft.fft(H_td, axis=1), axes=1))
            Hdd_list.append(DD)

        # 組合 desired / jammer / all
        doppler_ax = np.fft.fftshift(np.fft.fftfreq(N_T, d=T_sym))   # Hz
        delay_ax   = np.arange(N_DELAY) / W_delay * 1e9               # ns
        Dg, Tg     = np.meshgrid(delay_ax, doppler_ax)                # [N_T, N_DELAY]

        grids, labels = [], []
        for i in idx_des:
            grids.append(Hdd_list[i].T); labels.append(f"Des Tx{i}")
        for i in idx_jam:
            grids.append(Hdd_list[i].T); labels.append(f"Jam Tx{i}")
        if idx_des:
            grids.append(np.sum([Hdd_list[i] for i in idx_des], axis=0).T)
            labels.append("Des ALL")
        if idx_jam:
            grids.append(np.sum([Hdd_list[i] for i in idx_jam], axis=0).T)
            labels.append("Jam ALL")
        grids.append(np.sum(Hdd_list, axis=0).T); labels.append("ALL Tx")

        cols = min(3, len(grids))
        rows = int(np.ceil(len(grids) / cols))
        fig  = plt.figure(figsize=(cols * 5, rows * 4.5))
        fig.suptitle("Delay-Doppler Plots")

        for k, (Z, lbl) in enumerate(zip(grids, labels), start=1):
            ax = fig.add_subplot(rows, cols, k, projection="3d")
            ax.plot_surface(Dg, Tg, Z, cmap="viridis", edgecolor="none")
            ax.set_title(f"|{lbl}|")
            ax.set_xlabel("Delay (ns)")
            ax.set_ylabel("Doppler (Hz)")
            ax.set_zlabel("|H|")

        plt.tight_layout()
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        plt.savefig(output_path, dpi=150, bbox_inches="tight")
        plt.close(fig)
        return _verify(output_path)

    except SionnaLLVMError:
        plt.close("all")
        raise
    except Exception as e:
        logger.exception(f"生成 Doppler Plot 時出錯: {e}")
        plt.close("all")
        return False


# ── Channel Response Plot ─────────────────────────────────────────────────────
async def generate_channel_response(
    output_path: str = CHANNEL_RESP_PATH,
    tx_list: Optional[List[Tuple]] = None,
    rx_config: Optional[Tuple] = None,
) -> bool:
    """生成 H(t, f) 通道響應 3D 曲面圖（H_des / H_jam / H_all）"""
    logger.info("▶ 開始生成 Channel Response Plot...")
    _clean(output_path)

    try:
        load_scene, SionnaTX, SionnaRX, PlanarArray, PathSolver, subcarrier_frequencies, _ = _load_sionna()
        _setup_torch()

        if tx_list is None:
            tx_list = DEFAULT_TX_LIST + DEFAULT_JAM_LIST
        if rx_config is None:
            rx_config = DEFAULT_RX

        scene = _build_scene(load_scene, SionnaTX, SionnaRX, PlanarArray,
                             tx_list, rx_config, str(NYCU_XML))

        tx_names = list(scene.transmitters.keys())
        all_txs  = [scene.get(n) for n in tx_names]
        idx_des  = [i for i, tx in enumerate(all_txs) if getattr(tx, "role", None) == "desired"]
        idx_jam  = [i for i, tx in enumerate(all_txs) if getattr(tx, "role", None) == "jammer"]

        N_T  = 14       # OFDM 符號（一個 5G NR slot）
        N_F  = 76       # 子載波數
        SCS  = 30e3     # 子載波間距 Hz
        T_sym = 1.0 / SCS
        freqs_hz = np.array(subcarrier_frequencies(N_F, SCS))   # drjit 轉 numpy [N_F]

        a_cir, tau_cir = _solver_and_cir(scene, PathSolver,
                                         n_time=N_T, samp_freq=1.0/T_sym,
                                         normalize_delays=False, max_depth=10)

        tx_powers = [_dbm2w(scene.get(n).power_dbm) for n in tx_names]

        H_des = sum(_compute_H_tf(a_cir, tau_cir, i, tx_powers[i], freqs_hz) for i in idx_des) \
                if idx_des else np.zeros((N_T, N_F), dtype=complex)
        H_jam = sum(_compute_H_tf(a_cir, tau_cir, i, tx_powers[i], freqs_hz) for i in idx_jam) \
                if idx_jam else np.zeros((N_T, N_F), dtype=complex)
        H_all = H_des + H_jam

        T_mesh, F_mesh = np.meshgrid(np.arange(N_T), np.arange(N_F), indexing="ij")

        fig = plt.figure(figsize=(18, 5))
        for k, (H, title) in enumerate(
            [(H_des, "‖H_des‖"), (H_jam, "‖H_jam‖"), (H_all, "‖H_all‖")], 1
        ):
            ax = fig.add_subplot(1, 3, k, projection="3d")
            ax.plot_surface(F_mesh, T_mesh, np.abs(H), cmap="viridis", edgecolor="none")
            ax.set_xlabel("Subcarrier"); ax.set_ylabel("OFDM Symbol"); ax.set_title(title)
        plt.tight_layout()

        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        plt.savefig(output_path, dpi=150, bbox_inches="tight")
        plt.close(fig)
        return _verify(output_path)

    except SionnaLLVMError:
        plt.close("all")
        raise
    except Exception as e:
        logger.exception(f"生成 Channel Response Plot 時出錯: {e}")
        plt.close("all")
        return False
