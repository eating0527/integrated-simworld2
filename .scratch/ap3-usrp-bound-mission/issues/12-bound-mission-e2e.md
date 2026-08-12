# 12 — 驗證完整 Bound Mission 生命週期

**What to build:** 建立一套從 Device Health、Bound Start、執行中 Degraded／Recovery、AP3 Resume／Timeout、Best-Effort Stop、Retry Stop 到 Noise Upload／Completed 的整合驗證，確保前面各張 tickets 組合後仍遵守同一 mission 與獨立 child 生命週期。整理可由現場操作人員執行的硬體驗收清單。

**Blocked by:** 11 — 加入持久化的 5／15／30 秒自動重試.

**Status:** ready-for-agent

- [ ] 自動化 E2E 覆蓋 Both Ready → shared mission →雙邊 Running → Stop All → Noise Uploaded → Completed。
- [ ] 自動化 E2E 覆蓋任一 child launch failure → sibling 持續 → Degraded，且全程使用同一 `mission_id`。
- [ ] 自動化 E2E 覆蓋 RasPi Offline／Presumed running → AP3 繼續 → SSH recover／remote reconcile → Running。
- [ ] 自動化 E2E 覆蓋 AP3 freshness loss → 300 秒內 Resume → append 同一 GPS → Running。
- [ ] 自動化 E2E 覆蓋 AP3 Resume Timeout → Partial GPS Result → Noise 成功 → Completed with Warning／GPS Failed。
- [ ] 自動化 E2E 覆蓋一邊 Stop failure → 另一邊完成 → individual Retry Stop → Finalizing／terminal outcome。
- [ ] 自動化 E2E 覆蓋 immediate upload failure、5／15／30 retries exhaustion、Manual Retry recovery 與最終 Completed。
- [ ] 在關鍵流程中重新建立 Backend／Frontend 狀態，驗證 `capture.json` 可恢復 resume、stop 與 upload retry 進度。
- [ ] Frontend 無水平捲軸，狀態與按鈕在既有響應式斷點可操作，錯誤／Disabled／focus 語意符合既有可及性規範。
- [ ] Backend affected tests、Frontend affected tests 與 production build 全部通過。
- [ ] 產出實機驗收清單，涵蓋 AP3 拔插小於／大於五分鐘、RasPi 斷網恢復、單邊 Stop failure、Upload exhaustion 與 Manual Retry；一般自動測試不要求硬體存在。
- [ ] 若整合驗證發現跨-ticket 契約落差，修正後補上最小 regression test，不以放寬 spec 作為通過方式。
