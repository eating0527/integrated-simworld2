# GPS_N UNet Phase 4 Adapter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立 `gps_n` 專用 3-channel adapter，輸出順序固定為 `[sparse_rss, sampling_mask, building_height_norm]`。

**Architecture:** 在 `iss_unet_service.py` 加入新模型專用 RSS normalization helpers 與 input builder。此 phase 不載入模型、不跑 inference。

**Tech Stack:** Python, NumPy, pytest。

---

## Scope

本 phase 只處理資料轉換契約。`gps_n` 接模型在 Phase 5。

## Files

- Modify: `backend/app/iss_unet_service.py`
- Modify: `backend/tests/test_iss_unet_service.py`

## Task 1: Add GPS_N RSS Normalization Helpers

- [ ] **Step 1: Add constants**

Near `ISS_MIN_DBM` and `ISS_MAX_DBM`, add:

```python
GPSN_RSS_MIN_DBM = -90.0
GPSN_RSS_MAX_DBM = -15.0
```

- [ ] **Step 2: Add helper functions**

Add:

```python
def _normalize_gpsn_rss(values: np.ndarray) -> np.ndarray:
    clipped = np.clip(values.astype(np.float32), GPSN_RSS_MIN_DBM, GPSN_RSS_MAX_DBM)
    return (clipped - GPSN_RSS_MIN_DBM) / (GPSN_RSS_MAX_DBM - GPSN_RSS_MIN_DBM)


def _denormalize_gpsn_rss(values: np.ndarray) -> np.ndarray:
    return values.astype(np.float32) * (GPSN_RSS_MAX_DBM - GPSN_RSS_MIN_DBM) + GPSN_RSS_MIN_DBM
```

- [ ] **Step 3: Add normalization test**

Add:

```python
def test_gpsn_rss_normalization_uses_bundle_range(self):
    from app.iss_unet_service import _denormalize_gpsn_rss, _normalize_gpsn_rss

    values = np.array([-120.0, -90.0, -52.5, -15.0, 0.0], dtype=np.float32)
    norm = _normalize_gpsn_rss(values)
    expected = np.array([0.0, 0.0, 0.5, 1.0, 1.0], dtype=np.float32)
    np.testing.assert_allclose(norm, expected)
    np.testing.assert_allclose(_denormalize_gpsn_rss(np.array([0.0, 0.5, 1.0], dtype=np.float32)), np.array([-90.0, -52.5, -15.0], dtype=np.float32))
```

## Task 2: Add 3-Channel Input Builder

- [ ] **Step 1: Add builder**

Add:

```python
def build_gpsn_unet_input(
    sparse_values_dbm: np.ndarray,
    sparse_mask: np.ndarray,
    building_map: np.ndarray,
) -> np.ndarray:
    if sparse_values_dbm.shape != sparse_mask.shape or sparse_values_dbm.shape != building_map.shape:
        raise ValueError("sparse_values_dbm, sparse_mask, and building_map must have the same shape")
    building_norm = np.clip(building_map.astype(np.float32) / BUILDING_MAX_M, 0.0, 1.0)
    mask = sparse_mask.astype(np.float32)
    sparse_rss = _normalize_gpsn_rss(sparse_values_dbm) * mask
    return np.stack([sparse_rss, mask, building_norm], axis=0).astype(np.float32)
```

- [ ] **Step 2: Add channel order test**

Add:

```python
def test_build_gpsn_unet_input_uses_expected_channel_order(self):
    from app.iss_unet_service import build_gpsn_unet_input

    sparse_values = np.full((128, 128), -90.0, dtype=np.float32)
    sparse_values[3, 4] = -52.5
    sparse_mask = np.zeros((128, 128), dtype=np.float32)
    sparse_mask[3, 4] = 1.0
    building = np.zeros((128, 128), dtype=np.float32)
    building[3, 4] = 30.0

    inputs = build_gpsn_unet_input(sparse_values, sparse_mask, building)

    self.assertEqual(inputs.shape, (3, 128, 128))
    self.assertAlmostEqual(float(inputs[0, 3, 4]), 0.5)
    self.assertAlmostEqual(float(inputs[1, 3, 4]), 1.0)
    self.assertAlmostEqual(float(inputs[2, 3, 4]), 0.5)
    self.assertAlmostEqual(float(inputs[0, 0, 0]), 0.0)
```

- [ ] **Step 3: Add shape validation test**

Add:

```python
def test_build_gpsn_unet_input_rejects_shape_mismatch(self):
    from app.iss_unet_service import build_gpsn_unet_input

    with self.assertRaisesRegex(ValueError, "same shape"):
        build_gpsn_unet_input(
            np.zeros((128, 128), dtype=np.float32),
            np.zeros((64, 64), dtype=np.float32),
            np.zeros((128, 128), dtype=np.float32),
        )
```

## Task 3: Run Adapter Tests

- [ ] **Step 1: Run focused tests**

Run:

```powershell
cd backend
python -m pytest tests/test_iss_unet_service.py -k "gpsn_rss_normalization or build_gpsn_unet_input" -q
```

Expected: pass.

## Exit Criteria

- New normalization range is `[-90, -15] dBm`.
- 3-channel order is exactly `[sparse_rss, sampling_mask, building_height_norm]`.
- Adapter has direct unit tests before inference wiring.
