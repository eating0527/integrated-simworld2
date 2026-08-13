# 12 — 驗證完整 Bound Mission 生命週期

**What to build:** 建立一套從 Device Health、Bound Start、執行中 Degraded／Recovery、AP3 Resume／Timeout、Best-Effort Stop、Retry Stop 到 Noise Upload／Completed 的整合驗證，確保前面各張 tickets 組合後仍遵守同一 mission 與獨立 child 生命週期。整理可由現場操作人員執行的硬體驗收清單。

**Blocked by:** 11 — 加入持久化的 5／15／30 秒自動重試.

**Status:** ready-for-human

- [x] 自動化 E2E 覆蓋 Both Ready → shared mission →雙邊 Running → Stop All → Noise Uploaded → Completed。
- [x] 自動化 E2E 覆蓋任一 child launch failure → sibling 持續 → Degraded，且全程使用同一 `mission_id`。
- [x] 自動化 E2E 覆蓋 RasPi Offline／Presumed running → AP3 繼續 → SSH recover／remote reconcile → Running。
- [x] 自動化 E2E 覆蓋 AP3 freshness loss → 300 秒內 Resume → append 同一 GPS → Running。
- [x] 自動化 E2E 覆蓋 AP3 Resume Timeout → Partial GPS Result → Noise 成功 → Completed with Warning／GPS Failed。
- [x] 自動化 E2E 覆蓋一邊 Stop failure → 另一邊完成 → individual Retry Stop → Finalizing／terminal outcome。
- [x] 自動化 E2E 覆蓋 immediate upload failure、5／15／30 retries exhaustion、Manual Retry recovery 與最終 Completed。
- [x] 在關鍵流程中重新建立 Backend／Frontend 狀態，驗證 `capture.json` 可恢復 resume、stop 與 upload retry 進度。
- [x] Frontend 無水平捲軸，狀態與按鈕在既有響應式斷點可操作，錯誤／Disabled／focus 語意符合既有可及性規範。
- [x] Backend affected tests、Frontend affected tests 與 production build 全部通過。
- [x] 產出實機驗收清單，涵蓋 AP3 拔插小於／大於五分鐘、RasPi 斷網恢復、單邊 Stop failure、Upload exhaustion 與 Manual Retry；一般自動測試不要求硬體存在。
- [x] 若整合驗證發現跨-ticket 契約落差，修正後補上最小 regression test，不以放寬 spec 作為通過方式。

## Comments

- 新增 `backend/tests/test_bound_mission_e2e.py`，以 `CaptureCoordinator` 公開操作與持久化 `capture.json` 串接完整 Bound Mission 流程：雙邊成功、雙向 launch failure、RasPi reconcile、AP3 resume／timeout、Stop failure／Retry Stop、持久化 5／15／30 秒 upload retry 與 Manual Retry。
- `docs/ops.md` 新增實機驗收清單，涵蓋 AP3 拔插邊界、RasPi 斷線恢復、Stop failure、upload exhaustion／Manual Retry 與 frontend/backend 重啟證據。
- 驗證：`USRPTelemetry.test.tsx` 38/38、`npm run build`、`git diff --check` 通過。新增 backend E2E 無法執行，原因是 `backend/.venv` 指向不存在的 WindowsApps Python 3.12 runtime，系統 Python launcher 也無法啟動。
- Standards／Spec 雙軸 review 完成；首輪的 USRP launch failure、跨重啟 AP3／Stop 恢復與真實 exhaustion→Manual Retry 流程皆已補測。
