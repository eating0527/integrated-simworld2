# 05 — 加入 Single-Flight Polling 與 USRP Runtime Reconcile

**What to build:** 執行中的綁定任務遇到 Raspberry Pi 網路中斷時，Frontend 立即顯示 Noise Offline／Presumed running 與 Mission Degraded，AP3 繼續採樣；SSH 恢復後，系統以原 `mission_id` 讀取遠端狀態並恢復正確任務狀態。慢速 status request 不會重疊。

**Blocked by:** 04 — 完成 Bound Start 第一階段 Release.

**Status:** ready-for-human

- [x] Active status polling 等目前 request settle 後再等待約 2 秒才送下一次，不會累積重疊 GET。
- [x] Request timeout／abort 後仍能進入下一輪，且元件卸載後不再排程 polling。
- [x] Mission running 時 SSH 中斷會把 USRP Connection 設為 Offline；無法證明已停止時保留 Presumed running 與 Recording。
- [x] RasPi 斷線不停止 AP3、不改變 `mission_id`，Mission 顯示 Degraded 並指出 Noise Offline、GPS Recording。
- [x] SSH 恢復後只讀取相同 `mission_id` 的 remote mission state；確認仍 Running 才清除錯誤並把 Mission 恢復 Running。
- [x] Remote state 為 Stopped、Failed、Finalizing 或 Upload Pending 時，各自 reconcile 成對應 child 與 Overall State，不一律恢復 Running。
- [x] Reconcile 不建立新 mission、不擅自送出 stop 或 restart。
- [x] SSH、service probe 與 remote state read 都有 bounded timeout，且不阻塞 async server loop。
- [x] Backend adapter、Coordinator、API 與 Frontend fake-timer tests 涵蓋斷線、持續 degraded、恢復及 single-flight。

## Comments

- Frontend status polling 改為共用 single-flight request；每次 settle 後等待約 2 秒，timeout 後續輪，unmount 會取消在途 request 並停止排程。
- USRP runtime reconcile 使用原 `mission_id` 的輕量 service probe 與 remote mission state；斷線保留 Presumed running／Recording，恢復後依 Running、Stopped、Failed、Finalizing、Upload Pending 分流，未知證據不會誤報完成。
- `/api/capture/status` 將 coordinator 工作移至 thread 並以 30 秒 timeout 限制；SSH service probe 與 mission state read 各自有 bounded timeout，runtime polling 不抓 journal diagnostics。
- 驗證：USRPTelemetry 30/30、frontend production build、Python 3.11 `py_compile` 與 `git diff --check` 通過。完整 frontend 158/159；唯一失敗仍為既有 `SimulationPanel` mock 缺少 `response.text()`。Backend unittest 無法執行，因 repo `.venv` 指向已失效的 Python 3.12 launcher，而現有 Python 3.11 未安裝 FastAPI／Pydantic 等依賴。
- Standards／Spec 雙軸 review 後修正：缺少或不符 mission state、未知 upload state、service 尚未停止的 Failed／Stopped 證據皆維持保守 reconciliation；Spec 重審無 finding，Standards 重審的 timeout fallback 重複亦已收斂。
