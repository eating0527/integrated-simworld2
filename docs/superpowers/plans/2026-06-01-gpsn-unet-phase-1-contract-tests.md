# GPS_N UNet Phase 1 Contract Tests Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 先寫出會失敗的測試，明確鎖住 `sim/gps` 不載入 UNet、`gps_n` 將改走新模型的目標契約。

**Architecture:** 只修改測試，不修改 production code。測試要 patch 現有 loader 與 route sample，讓失敗原因直接指向目前 mode routing 還沒有拆開。

**Tech Stack:** Python, pytest, unittest.mock, NumPy。

---

## Scope

這個 phase 只建立測試保護網，不做功能修正。完成後預期會有 failing tests。

## Files

- Modify: `backend/tests/test_iss_unet_service.py`

## Task 1: Add `sim` Contract Test

- [ ] **Step 1: Write the failing test**

在 `backend/tests/test_iss_unet_service.py` 新增測試，patch `app.iss_unet_service._load_model`：

```python
def test_sim_reconstruction_does_not_load_unet_model(self):
    from app.iss_unet_service import ISSUNetCFARParams, reconstruct_iss_unet

    model_path = self.artifact_dir / "legacy_model.pth"
    model_path.write_bytes(b"legacy")

    with patch("app.iss_unet_service.MODEL_ARTIFACT_PATH", model_path):
        with patch("app.iss_unet_service.SCENE_DIR", self.scene_dir):
            with patch("app.iss_unet_service.OUTPUT_DIR", self.output_dir):
                with patch("app.iss_unet_service._load_model", side_effect=AssertionError("UNet should not load for sim")):
                    with patch("app.iss_unet_service._render_reconstructed_png", return_value=b"reconstructed"):
                        with patch("app.iss_unet_service._render_comparison_png", return_value=b"comparison"):
                            result = reconstruct_iss_unet(
                                scene="NTPU",
                                mode="sim",
                                cfar=ISSUNetCFARParams(enabled=False),
                            )

    self.assertEqual(result["mode"], "sim")
    self.assertFalse(result["metrics"]["model_inference"])
```

- [ ] **Step 2: Run the focused test**

Run:

```powershell
cd backend
python -m pytest tests/test_iss_unet_service.py -k "sim_reconstruction_does_not_load_unet_model" -q
```

Expected before Phase 2: fail with `AssertionError: UNet should not load for sim`.

## Task 2: Add `gps` Contract Test

- [ ] **Step 1: Write the failing test**

新增測試，patch `app.iss_real.create_route_sparse_sample` 回傳 deterministic route sample，並 patch `_load_model`：

```python
def test_gps_reconstruction_does_not_load_unet_model(self):
    from app.iss_real import RouteSparseResult
    from app.iss_unet_service import ISSUNetCFARParams, reconstruct_iss_unet

    model_path = self.artifact_dir / "legacy_model.pth"
    model_path.write_bytes(b"legacy")
    shape = (128, 128)
    sparse_mask = np.zeros(shape, dtype=np.float32)
    sparse_mask[4, 5] = 1.0
    outdoor_mask = np.ones(shape, dtype=np.float32)
    sparse_values = np.full(shape, -140.0, dtype=np.float32)
    sparse_values[4, 5] = -60.0
    route_sample = RouteSparseResult(
        sparse_mask=sparse_mask,
        outdoor_mask=outdoor_mask,
        iss_sparse_dbm=sparse_values,
        inputs=np.zeros((5, 128, 128), dtype=np.float32),
        metrics={"mode": "gps", "route_points": 1, "used_samples": 1, "aligned_noise": 0, "skipped_noise": 0, "sample_used": False},
    )

    with patch("app.iss_unet_service.MODEL_ARTIFACT_PATH", model_path):
        with patch("app.iss_unet_service.SCENE_DIR", self.scene_dir):
            with patch("app.iss_unet_service.OUTPUT_DIR", self.output_dir):
                with patch("app.iss_real.create_route_sparse_sample", return_value=route_sample):
                    with patch("app.iss_unet_service._load_model", side_effect=AssertionError("UNet should not load for gps")):
                        with patch("app.iss_unet_service._render_reconstructed_png", return_value=b"reconstructed"):
                            with patch("app.iss_unet_service._render_comparison_png", return_value=b"comparison"):
                                result = reconstruct_iss_unet(
                                    scene="NTPU",
                                    mode="gps",
                                    cfar=ISSUNetCFARParams(enabled=False),
                                )

    self.assertEqual(result["mode"], "gps")
    self.assertFalse(result["metrics"]["model_inference"])
```

- [ ] **Step 2: Run the focused test**

Run:

```powershell
cd backend
python -m pytest tests/test_iss_unet_service.py -k "gps_reconstruction_does_not_load_unet_model" -q
```

Expected before Phase 2: fail with `AssertionError: UNet should not load for gps`.

## Task 3: Add `gps_n` Routing Contract Test

- [ ] **Step 1: Write the failing test**

新增測試描述最終狀態：`gps_n` 不應呼叫舊 `_load_model`，而會呼叫新的 `_load_gpsn_model`。在 Phase 1 中這個 test 會因 `_load_gpsn_model` 尚未存在而失敗。

```python
def test_gpsn_reconstruction_uses_new_gpsn_model_loader(self):
    from app.iss_real import RouteSparseResult
    from app.iss_unet_service import ISSUNetCFARParams, reconstruct_iss_unet

    shape = (128, 128)
    sparse_mask = np.zeros(shape, dtype=np.float32)
    sparse_mask[10, 11] = 1.0
    outdoor_mask = np.ones(shape, dtype=np.float32)
    sparse_values = np.full(shape, -90.0, dtype=np.float32)
    sparse_values[10, 11] = -55.0
    route_sample = RouteSparseResult(
        sparse_mask=sparse_mask,
        outdoor_mask=outdoor_mask,
        iss_sparse_dbm=sparse_values,
        inputs=np.zeros((5, 128, 128), dtype=np.float32),
        metrics={"mode": "gps_n", "route_points": 1, "used_samples": 1, "aligned_noise": 1, "skipped_noise": 0, "sample_used": False},
    )

    class FakeModel:
        def __call__(self, tensor):
            import torch

            return torch.full((1, 1, 128, 128), 0.5, dtype=torch.float32, device=tensor.device)

    with patch("app.iss_unet_service.SCENE_DIR", self.scene_dir):
        with patch("app.iss_unet_service.OUTPUT_DIR", self.output_dir):
            with patch("app.iss_real.create_route_sparse_sample", return_value=route_sample):
                with patch("app.iss_unet_service._load_model", side_effect=AssertionError("legacy UNet should not load for gps_n")):
                    with patch("app.iss_unet_service._load_gpsn_model", return_value=(FakeModel(), "cpu")):
                        with patch("app.iss_unet_service._render_reconstructed_png", return_value=b"reconstructed"):
                            with patch("app.iss_unet_service._render_comparison_png", return_value=b"comparison"):
                                result = reconstruct_iss_unet(
                                    scene="NTPU",
                                    mode="gps_n",
                                    cfar=ISSUNetCFARParams(enabled=False),
                                    focus_sampling_points=False,
                                )

    self.assertEqual(result["mode"], "gps_n")
    self.assertTrue(result["metrics"]["model_inference"])
```

- [ ] **Step 2: Run the focused test**

Run:

```powershell
cd backend
python -m pytest tests/test_iss_unet_service.py -k "gpsn_reconstruction_uses_new_gpsn_model_loader" -q
```

Expected before Phase 5: fail because `_load_gpsn_model` is not implemented.

## Exit Criteria

- `sim` contract test exists and fails for the expected reason before Phase 2.
- `gps` contract test exists and fails for the expected reason before Phase 2.
- `gps_n` routing contract test exists and fails until the new loader is implemented.
- No production files are modified in this phase.
