# 08 — 實作並行 Best-Effort Stop All

**What to build:** 操作人員按下 Stop All 時，AP3 與 USRP 的停止／收尾同時開始；任一邊錯誤或 timeout 都不阻止另一邊完成。系統持續呈現每個 child 的真實結果，未知遠端程序不得被誤報為 Stopped 或 Completed。

**Blocked by:** 05 — 加入 Single-Flight Polling 與 USRP Runtime Reconcile; 07 — 完成 AP3 五分鐘自動接續.

**Status:** ready-for-agent

- [ ] Stop All 的 AP3 與 USRP stop attempts 並行開始，不以先完成 AP3 再開始 USRP 的方式串行執行。
- [ ] 一邊 exception、timeout 或 finalize failure 時，另一邊仍會被嘗試並保存自己的最終結果。
- [ ] Stop All 已被要求的事實與時間持久化，page／backend restart 後不會恢復成尚未停止的 UI。
- [ ] 可確認停止的 child 正確進入 Stopped，並依檔案狀態進入 Ready、Upload Pending 或 Uploaded。
- [ ] SSH 中斷或 stop result 未知時，USRP 保持 Presumed running／reconciling 或 stop-failed，不會假造 Stopped。
- [ ] 任一程序仍不確定時 Mission 不會 Completed；依 child 狀態呈現 Stopping、Degraded 或 Finalizing。
- [ ] AP3 finalize 保留 Resume Timeout 前的 Partial GPS Result，不因 service failure 刪除有效 rows。
- [ ] Stop All response 與後續 status 都能獨立呈現兩個 child 的結果與錯誤。
- [ ] 測試證明兩個 stop attempt 真的可同時進行、單邊失敗隔離、持久化正確及 upload callback／status 不造成 concurrent write corruption。
