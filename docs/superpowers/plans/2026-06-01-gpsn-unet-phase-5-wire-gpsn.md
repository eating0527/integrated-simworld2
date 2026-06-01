# GPS_N UNet Phase 5 Wire GPS_N Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 讓 `gps_n` 正式使用新的 3-channel UNet checkpoint 推論，並停止使用舊 5-channel `_load_model`。

**Architecture:** 新增 `_load_gpsn_model` 與 `_run_gpsn_unet`。`reconstruct_iss_unet` 的 mode routing 變成 `sim/gps` 不跑模型、`gps_n` 跑新模型。

**Tech Stack:** Python, PyTorch, NumPy, pytest。

---

## Scope

本 phase 不再修改模型架構本身。此階段接線依賴 Phase 3 的 `model_unet_single.py` 與 Phase 4 的 adapter。

## Files

- Modify: `backend/app/iss_unet_service.py`
- Modify: `backend/tests/test_iss_unet_service.py`

## Task 1: Add GPS_N Model Path And Loader

- [ ] **Step 1: Add artifact path**

Near `MODEL_ARTIFACT_PATH`, add:

```python
GPSN_MODEL_ARTIFACT_PATH = BASE_DIR / "model_artifacts" / "unet_single" / "best_model.pt"
```

- [ ] **Step 2: Add loader**

Add:

```python
def _load_gpsn_model(device: str):
    import torch

    from app.model_unet_single import UNet

    torch_device = torch.device(device if device == "cuda" and torch.cuda.is_available() else "cpu")
    checkpoint = torch.load(GPSN_MODEL_ARTIFACT_PATH, map_location=torch_device, weights_only=True)
    model = UNet(in_channels=3, out_channels=1).to(torch_device)
    model.load_state_dict(checkpoint["model_state_dict"])
    model.eval()
    return model, torch_device
```

- [ ] **Step 3: Update status response**

In `iss_unet_status()`, add:

```python
"legacy_model": {"available": MODEL_ARTIFACT_PATH.exists()},
"gpsn_model": {"available": GPSN_MODEL_ARTIFACT_PATH.exists()},
```

Keep existing `"model"` key during transition if frontend or tests depend on it.

## Task 2: Add GPS_N Inference Runner

- [ ] **Step 1: Add `_run_gpsn_unet`**

Add:

```python
def _run_gpsn_unet(
    sparse_values_dbm: np.ndarray,
    sparse_mask: np.ndarray,
    building_map: np.ndarray,
    device: str,
) -> np.ndarray:
    import torch

    model, torch_device = _load_gpsn_model(device)
    inputs = build_gpsn_unet_input(sparse_values_dbm, sparse_mask, building_map)
    tensor = torch.from_numpy(inputs).float().unsqueeze(0).to(torch_device)
    with torch.no_grad():
        output = model(tensor)
    prediction = output[0, 0].detach().cpu().numpy()
    prediction = np.clip(prediction, 0.0, 1.0)
    return _denormalize_gpsn_rss(prediction).astype(np.float32)
```

- [ ] **Step 2: Add runner test**

Patch `_load_gpsn_model` to return fake model output `0.5` and verify denormalized output is `-52.5 dBm`:

```python
def test_run_gpsn_unet_denormalizes_model_output(self):
    from app.iss_unet_service import _run_gpsn_unet

    class FakeModel:
        def __call__(self, tensor):
            import torch

            return torch.full((1, 1, 128, 128), 0.5, dtype=torch.float32, device=tensor.device)

    sparse_values = np.full((128, 128), -90.0, dtype=np.float32)
    sparse_mask = np.zeros((128, 128), dtype=np.float32)
    building = np.zeros((128, 128), dtype=np.float32)

    with patch("app.iss_unet_service._load_gpsn_model", return_value=(FakeModel(), "cpu")):
        result = _run_gpsn_unet(sparse_values, sparse_mask, building, "cpu")

    self.assertEqual(result.shape, (128, 128))
    self.assertAlmostEqual(float(result[0, 0]), -52.5)
```

## Task 3: Route `gps_n` To New Runner

- [ ] **Step 1: Replace temporary `gps_n` inference path**

In `reconstruct_iss_unet`, use:

```python
if mode in {"sim", "gps"}:
    reconstructed_iss = _reconstruct_without_model(arrays, mode)
    model_inference = False
else:
    if sparse_values_dbm is None:
        raise RuntimeError("gps_n sparse values are required for UNet inference")
    reconstructed_iss = _run_gpsn_unet(
        sparse_values_dbm=sparse_values_dbm,
        sparse_mask=sparse_mask,
        building_map=arrays["building"],
        device=device,
    )
    model_inference = True
```

- [ ] **Step 2: Keep focus sampling post-processing**

Leave this behavior after inference:

```python
if mode == "gps_n" and focus_sampling_points:
    reconstructed_iss, confidence_metrics = apply_noise_confidence_weighting(...)
```

- [ ] **Step 3: Run routing contract test**

Run:

```powershell
cd backend
python -m pytest tests/test_iss_unet_service.py -k "gpsn_reconstruction_uses_new_gpsn_model_loader" -q
```

Expected: pass.

## Task 4: Run Focused GPS_N Tests

- [ ] **Step 1: Run focused tests**

Run:

```powershell
cd backend
python -m pytest tests/test_iss_unet_service.py -k "gps_n or gpsn" -q
```

Expected: pass.

## Exit Criteria

- `gps_n` calls `_load_gpsn_model`.
- `gps_n` does not call `_load_model`.
- `gps_n` model input is 3-channel.
- `metrics.model_inference == True` for `gps_n`.
