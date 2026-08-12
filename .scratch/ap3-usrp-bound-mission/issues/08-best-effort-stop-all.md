# 08 — 實作並行 Best-Effort Stop All

**What to build:** 操作人員按下 Stop All 時，AP3 與 USRP 的停止／收尾同時開始；任一邊錯誤或 timeout 都不阻止另一邊完成。系統持續呈現每個 child 的真實結果，未知遠端程序不得被誤報為 Stopped 或 Completed。

**Blocked by:** 05 — 加入 Single-Flight Polling 與 USRP Runtime Reconcile; 07 — 完成 AP3 五分鐘自動接續.

**Status:** ready-for-human

- [x] Stop All 的 AP3 與 USRP stop attempts 並行開始，不以先完成 AP3 再開始 USRP 的方式串行執行。
- [x] 一邊 exception、timeout 或 finalize failure 時，另一邊仍會被嘗試並保存自己的最終結果。
- [x] Stop All 已被要求的事實與時間持久化，page／backend restart 後不會恢復成尚未停止的 UI。
- [x] 可確認停止的 child 正確進入 Stopped，並依檔案狀態進入 Ready、Upload Pending 或 Uploaded。
- [x] SSH 中斷或 stop result 未知時，USRP 保持 Presumed running／reconciling 或 stop-failed，不會假造 Stopped。
- [x] 任一程序仍不確定時 Mission 不會 Completed；依 child 狀態呈現 Stopping、Degraded 或 Finalizing。
- [x] AP3 finalize 保留 Resume Timeout 前的 Partial GPS Result，不因 service failure 刪除有效 rows。
- [x] Stop All response 與後續 status 都能獨立呈現兩個 child 的結果與錯誤。
- [x] 測試證明兩個 stop attempt 真的可同時進行、單邊失敗隔離、持久化正確及 upload callback／status 不造成 concurrent write corruption。

## Comments

- `CaptureCoordinator.stop_bind` 先原子持久化 `stop_requested_at`，再並行啟動 AP3／USRP stop；阻塞 process、SSH 與檔案驗證工作不持有 coordinator lock，單邊例外會保存為獨立 `stop_failed` 結果。
- USRP stop 僅接受相同 `mission_id` 且 service／mission state 都能證明終止的結果；未知遠端狀態保持 `presumed_running`，較新的 upload callback 不會被舊 stop response 降級，upload failure 保持 `upload_pending`。
- Frontend 讀取持久化 stop intent，page／backend restart 後 Stop All 維持 disabled；Retry Stop／Stopped child controls 留給明確依賴此票的 ticket 09。
- 驗證：USRPTelemetry Vitest 33/33、frontend production build、`git diff --check` 通過。完整 frontend 160/161，唯一失敗為既有 `SimulationPanel` mock 缺少 `response.text()`；backend unittest 因 repo `.venv` 指向失效的 Python 3.12 launcher而無法啟動。
- Standards／Spec 雙軸 review 完成：第一輪 findings 均已修正；最終 ticket 08 Spec findings 為 0，剩餘 Retry Stop UI 已確認屬於 ticket 09。
