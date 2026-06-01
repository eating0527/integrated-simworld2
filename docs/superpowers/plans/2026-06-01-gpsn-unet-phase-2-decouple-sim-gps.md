# GPS_N UNet Phase 2 Decouple Sim GPS Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 讓 `sim` 與 `gps` reconstruction 不再載入或執行舊 5-channel UNet。

**Architecture:** 在 `reconstruct_iss_unet` 內建立 mode-specific routing。`sim/gps` 使用已載入的 Sionna-backed arrays 與 route metrics 產生輸出；`gps_n` 暫時保留舊路徑，等 Phase 5 接新模型。

**Tech Stack:** Python, NumPy, Matplotlib render helpers, pytest。

---

## Scope

本 phase 不導入新模型、不處理權重、不新增 3-channel adapter。只拆開 `sim/gps` 和 `_load_model` 的依賴。

## Files

- Modify: `backend/app/iss_unet_service.py`
- Modify: `backend/tests/test_iss_unet_service.py`

## Task 1: Add Reconstruction Helper For Non-Model Modes

- [ ] **Step 1: Add helper near `reconstruct_iss_unet`**

Add:

```python
def _reconstruct_without_model(
    arrays: dict[str, np.ndarray],
    mode: str,
) -> np.ndarray:
    if mode not in {"sim", "gps"}:
        raise ValueError("mode must be sim or gps")
    return _clip_radio_map(arrays["iss"])
```

Rationale:

```text
sim/gps target is Sionna-backed inference, so both should use dense arrays["iss"].
gps still keeps route metrics and sparse overlays for comparison rendering.
```

- [ ] **Step 2: Add helper unit test**

Add:

```python
def test_reconstruct_without_model_returns_clipped_sionna_map(self):
    from app.iss_unet_service import _reconstruct_without_model

    arrays = {"iss": np.array([[-200.0, -60.0], [-20.0, -35.0]], dtype=np.float32)}
    result = _reconstruct_without_model(arrays, "sim")
    expected = np.array([[-140.0, -60.0], [-35.0, -35.0]], dtype=np.float32)
    np.testing.assert_allclose(result, expected)
```

- [ ] **Step 3: Run helper test**

Run:

```powershell
cd backend
python -m pytest tests/test_iss_unet_service.py -k "reconstruct_without_model" -q
```

Expected: pass.

## Task 2: Route `sim/gps` Around `_load_model`

- [ ] **Step 1: Change inference block**

In `reconstruct_iss_unet`, replace the shared model inference block with:

```python
model_inference = False
if mode in {"sim", "gps"}:
    reconstructed_iss = _reconstruct_without_model(arrays, mode)
else:
    import torch

    model, torch_device = _load_model(device)
    tensor = torch.from_numpy(inputs).float().unsqueeze(0).to(torch_device)
    with torch.no_grad():
        output = model(tensor)
    reconstructed_norm = output[0, 0].detach().cpu().numpy()
    reconstructed_iss = _clip_radio_map(_denormalize_iss(reconstructed_norm))
    model_inference = True
```

- [ ] **Step 2: Add metric**

Inside the existing `metrics` dict, add:

```python
"model_inference": model_inference,
```

- [ ] **Step 3: Keep existing render path**

Do not change:

```python
_render_reconstructed_png(...)
_render_comparison_png(...)
_cfar_detect(...)
np.save(...)
```

These should continue using `reconstructed_iss`.

## Task 3: Verify Phase 1 Tests For `sim/gps`

- [ ] **Step 1: Run `sim` contract test**

Run:

```powershell
cd backend
python -m pytest tests/test_iss_unet_service.py -k "sim_reconstruction_does_not_load_unet_model" -q
```

Expected: pass.

- [ ] **Step 2: Run `gps` contract test**

Run:

```powershell
cd backend
python -m pytest tests/test_iss_unet_service.py -k "gps_reconstruction_does_not_load_unet_model" -q
```

Expected: pass.

- [ ] **Step 3: Run focused mode tests**

Run:

```powershell
cd backend
python -m pytest tests/test_iss_unet_service.py -k "sim or gps" -q
```

Expected: existing `sim/gps` behavior tests pass, except tests explicitly waiting for Phase 5.

## Exit Criteria

- `sim` reconstruction does not call `_load_model`.
- `gps` reconstruction does not call `_load_model`.
- API response includes `metrics.model_inference == False` for `sim/gps`.
- `gps_n` is not considered complete in this phase.
