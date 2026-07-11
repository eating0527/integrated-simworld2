# GPS_N UNet Phase 6 Verification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 完成整體回歸驗證、API smoke test、權重未追蹤檢查，並準備提交。

**Architecture:** 不新增功能，只驗證 Phase 1-5 的整合結果。若驗證發現缺陷，回到對應 phase 修正。

**Tech Stack:** PowerShell, pytest, FastAPI runtime, git。

---

## Scope

本 phase 是驗證與提交前整理。除非測試揭露 bug，否則不改 production code。

## Files

- No required code changes.
- Stage files changed by previous phases after verification.

## Task 1: Run Backend Tests

- [ ] **Step 1: Run ISS_UNET focused suite**

Run:

```powershell
cd backend
python -m pytest tests/test_iss_unet_service.py -q
```

Expected: pass.

- [ ] **Step 2: Run generated scene regression tests**

Run:

```powershell
cd backend
python -m pytest tests/test_generated_scene_index.py -q
```

Expected: pass.

## Task 2: Check Model Artifact Safety

- [ ] **Step 1: Check normal git status**

Run:

```powershell
git status --short
```

Expected tracked changes include source and docs only. The checkpoint file must not appear as `??`.

- [ ] **Step 2: Check ignored artifact status**

Run:

```powershell
git status --short --ignored backend\app\model_artifacts
```

Expected output includes ignored artifact lines like:

```text
!! backend/app/model_artifacts/
```

- [ ] **Step 3: Check diff has no binary weight**

Run:

```powershell
git diff --stat
git diff --name-only
```

Expected: no `.pt` or `.pth` file appears.

## Task 3: API Smoke Test

- [ ] **Step 1: Start backend**

Use the repo's existing backend start command. If a documented command is unavailable, run the command already used by this project for FastAPI development.

- [ ] **Step 2: Check status endpoint**

Run:

```powershell
Invoke-RestMethod -Method Get http://localhost:8000/api/iss-unet/status
```

Expected response includes:

```text
torch.available = true
gpsn_model.available = true
```

- [ ] **Step 3: Smoke `sim` reconstruction**

Call the existing `sim` reconstruction endpoint with a known scene. Expected:

```text
mode = sim
metrics.model_inference = false
images.reconstructed is present
```

- [ ] **Step 4: Smoke `gps` reconstruction**

Call the existing `gps` reconstruction endpoint with sample or uploaded GPS data. Expected:

```text
mode = gps
metrics.model_inference = false
images.comparison is present
```

- [ ] **Step 5: Smoke `gps_n` reconstruction**

Call the existing `gps_n` reconstruction endpoint with GPS and noise inputs. Expected:

```text
mode = gps_n
metrics.model_inference = true
images.reconstructed is present
```

## Task 4: Review And Commit

- [ ] **Step 1: Review critical diff**

Run:

```powershell
git diff -- backend/app/iss_unet_service.py backend/app/model_unet_single.py backend/tests/test_iss_unet_service.py .gitignore docs/superpowers/plans
```

Confirm:

```text
sim/gps do not call _load_model
gps_n calls _load_gpsn_model
3-channel order is sparse_rss, sampling_mask, building_height_norm
weights are not in git diff
```

- [ ] **Step 2: Stage source, tests, and docs only**

Run:

```powershell
git add backend/app/iss_unet_service.py backend/app/model_unet_single.py backend/tests/test_iss_unet_service.py .gitignore docs/superpowers/plans
```

- [ ] **Step 3: Commit**

Use caveman-commit style:

```powershell
git commit -m "feat: route gpsn through new unet"
```

## Exit Criteria

- Backend tests pass.
- API smoke tests confirm mode routing.
- Git status shows no tracked model weights.
- Commit contains source, tests, docs, and `.gitignore` only.
