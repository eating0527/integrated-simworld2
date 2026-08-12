# 05 — 加入 Single-Flight Polling 與 USRP Runtime Reconcile

**What to build:** 執行中的綁定任務遇到 Raspberry Pi 網路中斷時，Frontend 立即顯示 Noise Offline／Presumed running 與 Mission Degraded，AP3 繼續採樣；SSH 恢復後，系統以原 `mission_id` 讀取遠端狀態並恢復正確任務狀態。慢速 status request 不會重疊。

**Blocked by:** 04 — 完成 Bound Start 第一階段 Release.

**Status:** ready-for-agent

- [ ] Active status polling 等目前 request settle 後再等待約 2 秒才送下一次，不會累積重疊 GET。
- [ ] Request timeout／abort 後仍能進入下一輪，且元件卸載後不再排程 polling。
- [ ] Mission running 時 SSH 中斷會把 USRP Connection 設為 Offline；無法證明已停止時保留 Presumed running 與 Recording。
- [ ] RasPi 斷線不停止 AP3、不改變 `mission_id`，Mission 顯示 Degraded 並指出 Noise Offline、GPS Recording。
- [ ] SSH 恢復後只讀取相同 `mission_id` 的 remote mission state；確認仍 Running 才清除錯誤並把 Mission 恢復 Running。
- [ ] Remote state 為 Stopped、Failed、Finalizing 或 Upload Pending 時，各自 reconcile 成對應 child 與 Overall State，不一律恢復 Running。
- [ ] Reconcile 不建立新 mission、不擅自送出 stop 或 restart。
- [ ] SSH、service probe 與 remote state read 都有 bounded timeout，且不阻塞 async server loop。
- [ ] Backend adapter、Coordinator、API 與 Frontend fake-timer tests 涵蓋斷線、持續 degraded、恢復及 single-flight。
