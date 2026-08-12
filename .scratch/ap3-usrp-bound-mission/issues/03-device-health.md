# 03 — 分離 Device Health 與 Mission Child State

**What to build:** 即使沒有執行中的任務，操作人員仍能在前端分別看到 AP3 與 Raspberry Pi 是否可參與新任務；裝置後續拔除或恢復不會改寫已完成任務的歷史 child 結果。

**Blocked by:** 02 — 建立 Mission State Contract 與前端狀態摘要.

**Status:** ready-for-agent

- [ ] Status contract 將 AP3／RasPi 的即時 Device Health 與目前或歷史 Mission Child State 分開回傳。
- [ ] AP3 Health 使用 bounded、lightweight 的 ADB 裝置與 forwarding readiness 檢查，只回答能否開始 Capture。
- [ ] RasPi Health 使用 bounded SSH 與簡單 service-state probe；heartbeat 不執行完整 logs、journal 或重型 diagnostics。
- [ ] Ready 狀態約每 10 秒檢查；Offline 依序使用 5、10、20、30 秒 backoff，之後維持最多 30 秒直到恢復。
- [ ] Health timeout 或 stale result 不得顯示 Ready，且回傳可辨識裝置與最近檢查時間的錯誤資訊。
- [ ] AP3／RasPi 拔除與恢復可在不重新整理頁面的情況下更新。
- [ ] 完成任務後再拔除裝置，只改變 Device Health，不把任務 child 或 Mission Overall State 改成 Failed。
- [ ] 前端分別顯示 AP3 與 Raspberry Pi 的 Ready／Offline，而非泛用 Capture unavailable。
- [ ] 自動測試使用 fake ADB／SSH、可控時間與持久化任務，涵蓋 Ready、Offline、backoff、恢復及歷史狀態不變。
