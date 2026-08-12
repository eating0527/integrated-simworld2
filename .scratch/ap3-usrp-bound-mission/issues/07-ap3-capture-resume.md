# 07 — 完成 AP3 五分鐘自動接續

**What to build:** AP3 短暫斷線後，在最後有效 GPS 的 300 秒期限內自動沿用原 `mission_id` 並 append 同一份 GPS 檔案；超過期限則顯示 Resume Timeout、保留 Partial GPS Result，但不接續、不補值，也不影響 USRP。

**Blocked by:** 01 — 統一 GPS CSV Schema; 06 — 偵測 AP3 GPS Freshness 中斷.

**Status:** ready-for-agent

- [ ] 原 Bound Mission 尚未 Stop／Finalizing／terminal，且 gap 小於或等於 300 秒時，AP3 可自動 Resume。
- [ ] 299 秒與 300 秒可接續；大於 300 秒不可接續，邊界由可控時間測試鎖定。
- [ ] Resume 沿用原 `mission_id` 與 GPS 路徑，append 時不 truncate 既有 rows、不重複 header、不補造中斷資料。
- [ ] Recorder process 仍存活與 process 已結束需採用安全的各自恢復路徑，但都遵守同一 300 秒限制。
- [ ] Resume 前驗證 canonical GPS schema；不合法時拒絕接續並保留原檔案與明確錯誤。
- [ ] Backend restart 後可由持久化時間與 GPS 最後可解析 row 恢復 Resume／Timeout 判斷，不把額度重置。
- [ ] Resume Timeout 後 AP3 child 維持失敗／不完整，GPS file 若有有效 rows 則 finalize 為 Partial GPS Result。
- [ ] AP3 Device Health 後續可恢復 Ready，但不改寫該舊 mission，也不自動建立新 mission。
- [ ] Frontend 顯示 Resume Timeout 與 Partial GPS file available；USRP 繼續採樣並維持原 `mission_id`。
- [ ] Resume 與 Stop／status 併發時使用既有鎖定與原子寫入，不會在 Stop 後重新啟動 recorder。
