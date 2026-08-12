# 11 — 加入持久化的 5／15／30 秒自動重試

**What to build:** Immediate Noise upload 失敗後，系統依序等待 5、15、30 秒執行三次有限自動重試；Frontend 顯示倒數與執行經過時間。三次皆失敗才顯示 `自動重試已用盡`，並保留不會重置自動額度的 Manual Retry。

**Blocked by:** 10 — 建立背景 Noise Upload 與 Manual Retry.

**Status:** ready-for-agent

- [ ] Immediate upload 失敗後排程 Retry 1/3 於 5 秒、Retry 2/3 於 15 秒、Retry 3/3 於 30 秒後執行。
- [ ] Waiting 狀態前端顯示 `自動重試 N/3 (X s)`，倒數由持久化 server timestamp 推導並每秒更新。
- [ ] Running 狀態前端顯示 `正在重試 N/3 (X s)`，elapsed time 每秒更新。
- [ ] 單次 timeout 或非-timeout failure 不顯示額外暫態訊息，直接進入下一次 retry countdown。
- [ ] 只有三次 delayed retries 全部失敗後才顯示 `自動重試已用盡`，File 維持 Upload Pending。
- [ ] Retry mode、state、attempt、maximum、next-attempt time、active-start time 與 last error 持久化於任務來源。
- [ ] Backend restart 後接續尚未完成的 schedule，不重置 attempt、不重複已完成 attempt，也不平行啟動兩個相同 upload job。
- [ ] 任一 automatic retry 成功時停止後續 schedule、標示 Uploaded、清除 pending retry state 並正確聚合 Mission。
- [ ] Manual Retry 不重置或改寫 automatic attempt history；執行中維持 `手動重試 (X s)`，失敗後仍可再次操作。
- [ ] 使用 controllable clock、fake jobs 與 Frontend fake timers 測試 5／15／30 秒邊界、顯示文字、exhaustion、restart restoration 與 no overlap。
