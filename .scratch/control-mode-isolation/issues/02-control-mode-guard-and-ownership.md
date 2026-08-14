# 02 — Control Mode 守門與任務所有權

**What to build:** 保留 Bound Capture 的共享 mission ID、雙端 preflight、各 child 獨立生命週期與 Stop All，同時避免 Bound Mission 與 Independent Capture 混合執行。使用者可隨時按 Bound／Independent 切換控制模式；若有未結案任務，維持原模式、絕不自動停止，並顯示明確的中文提示。

**Blocked by:** 01 — Independent Capture 與 GPS 無資料容忍.

**Status:** ready-for-human

- [x] 建立 Bound Capture 時，若任一 Independent GPS 或 Noise 任務未結案即拒絕；建立 Independent GPS 或 Noise 時，若 Bound Mission 未結案即拒絕。
- [x] Bound Capture 維持同一個 mission ID、雙端 preflight、獨立 child 生命週期與既有 Stop All 行為。
- [x] Bound／Independent 切換按鈕在未結案任務時仍可點擊，但不送出 Stop 請求、不顯示二次確認，且不切換目前模式。
- [x] 切換被阻擋時依狀態顯示：`請先停止 GPS 任務。`、`請先停止 Noise 任務。`、`請先停止 GPS 與 Noise 任務。`、`請先停止當前任務。`；Noise 上傳中或待上傳顯示 `請先等待 Noise 上傳。`。
- [x] Completed、Failed 與 Resume Timeout 不阻擋切換；未結案定義包含執行、推定執行、停止、停止失敗、Reconciling、檔案處理與上傳／重試中的狀態。
- [x] 加入後端與前端回歸測試，驗證跨模式拒絕、切換提示與無自動停止。

## Comments

- 後端以 Bound／Independent ownership guard 阻擋未結案任務混用；同一 Control Mode 的 GPS 與 Noise 仍可並行。
- 前端切換按鈕在未結案時保持可操作，使用 `role="alert"` 顯示指定提示，切換事件不呼叫 Stop API。
- 驗證：後端 290 tests、前端 176 tests 與 frontend production build 通過。
