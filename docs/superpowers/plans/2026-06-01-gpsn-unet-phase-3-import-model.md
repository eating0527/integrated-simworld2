# GPS_N UNet Phase 3 Import Model Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 將新 3-channel UNet 的模型架構納入專案，並確保 checkpoint 權重只存在本機且不會被 git 追蹤。

**Architecture:** 把 bundle 的 `models/unet.py` 架構複製成專案 module `backend/app/model_unet_single.py`。權重放入 `backend/app/model_artifacts/unet_single/best_model.pt`，透過 `.gitignore` 排除。

**Tech Stack:** Python, PyTorch, PowerShell, git ignore rules。

---

## Scope

本 phase 只處理模型 class 與權重安全，不把 `gps_n` 接到 inference。

## Files

- Create: `backend/app/model_unet_single.py`
- Modify: `.gitignore`
- Modify: `backend/tests/test_iss_unet_service.py`

## Task 1: Add Model Architecture

- [ ] **Step 1: Create `backend/app/model_unet_single.py`**

Copy only architecture code from:

```text
C:\Users\pinkie\Desktop\unet_single_input_bundle\models\unet.py
```

Expected file content:

```python
import torch
import torch.nn as nn


class ConvBlock(nn.Module):
    """Conv -> BN -> ReLU -> Conv -> BN -> ReLU"""

    def __init__(self, in_ch, out_ch):
        super().__init__()
        self.block = nn.Sequential(
            nn.Conv2d(in_ch, out_ch, 3, padding=1, bias=False),
            nn.BatchNorm2d(out_ch),
            nn.ReLU(inplace=True),
            nn.Conv2d(out_ch, out_ch, 3, padding=1, bias=False),
            nn.BatchNorm2d(out_ch),
            nn.ReLU(inplace=True),
        )

    def forward(self, x):
        return self.block(x)


class UNet(nn.Module):
    def __init__(self, in_channels=3, out_channels=1, features=(64, 128, 256, 512)):
        super().__init__()
        self.encoders = nn.ModuleList()
        self.pools = nn.ModuleList()
        prev_ch = in_channels
        for feature_count in features:
            self.encoders.append(ConvBlock(prev_ch, feature_count))
            self.pools.append(nn.MaxPool2d(2))
            prev_ch = feature_count

        self.bottleneck = ConvBlock(features[-1], features[-1] * 2)

        self.upconvs = nn.ModuleList()
        self.decoders = nn.ModuleList()
        prev_ch = features[-1] * 2
        for feature_count in reversed(features):
            self.upconvs.append(nn.ConvTranspose2d(prev_ch, feature_count, 2, stride=2))
            self.decoders.append(ConvBlock(feature_count * 2, feature_count))
            prev_ch = feature_count

        self.head = nn.Sequential(
            nn.Conv2d(features[0], out_channels, 1),
            nn.Sigmoid(),
        )

    def forward(self, x):
        skips = []
        for encoder, pool in zip(self.encoders, self.pools):
            x = encoder(x)
            skips.append(x)
            x = pool(x)

        x = self.bottleneck(x)

        for upconv, decoder, skip in zip(self.upconvs, self.decoders, reversed(skips)):
            x = upconv(x)
            x = torch.cat([x, skip], dim=1)
            x = decoder(x)

        return self.head(x)
```

- [ ] **Step 2: Add shape test**

Add:

```python
def test_single_input_unet_accepts_three_channels(self):
    import torch

    from app.model_unet_single import UNet

    model = UNet(in_channels=3, out_channels=1)
    model.eval()
    with torch.no_grad():
        output = model(torch.zeros((1, 3, 128, 128), dtype=torch.float32))
    self.assertEqual(tuple(output.shape), (1, 1, 128, 128))
```

- [ ] **Step 3: Run shape test**

Run:

```powershell
cd backend
python -m pytest tests/test_iss_unet_service.py -k "single_input_unet_accepts_three_channels" -q
```

Expected: pass when PyTorch is installed.

## Task 2: Protect Model Weights From Git

- [ ] **Step 1: Update `.gitignore`**

Ensure these patterns exist:

```gitignore
backend/app/model_artifacts/
*.pt
*.pth
```

- [ ] **Step 2: Copy checkpoint locally**

Run:

```powershell
New-Item -ItemType Directory -Force backend\app\model_artifacts\unet_single
Copy-Item C:\Users\pinkie\Desktop\unet_single_input_bundle\results\recon_raw\unet_s12_canonical_weighted\best_model.pt backend\app\model_artifacts\unet_single\best_model.pt
```

- [ ] **Step 3: Verify checkpoint is ignored**

Run:

```powershell
git status --short --ignored backend\app\model_artifacts\unet_single\best_model.pt
```

Expected:

```text
!! backend/app/model_artifacts/unet_single/best_model.pt
```

## Exit Criteria

- `backend/app/model_unet_single.py` is tracked source code.
- `backend/app/model_artifacts/unet_single/best_model.pt` exists locally.
- `.pt` and `.pth` files are ignored.
- No checkpoint bytes appear in `git diff`.
