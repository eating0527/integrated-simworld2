# 07 — 完成 AP3 五分鐘自動接續

**What to build:** AP3 短暫斷線後，在最後有效 GPS 的 300 秒期限內自動沿用原 `mission_id` 並 append 同一份 GPS 檔案；超過期限則顯示 Resume Timeout、保留 Partial GPS Result，但不接續、不補值，也不影響 USRP。

**Blocked by:** 01 — 統一 GPS CSV Schema; 06 — 偵測 AP3 GPS Freshness 中斷.

**Status:** ready-for-human

- [x] 原 Bound Mission 尚未 Stop／Finalizing／terminal，且 gap 小於或等於 300 秒時，AP3 可自動 Resume。
- [x] 299 秒與 300 秒可接續；大於 300 秒不可接續，邊界由可控時間測試鎖定。
- [x] Resume 沿用原 `mission_id` 與 GPS 路徑，append 時不 truncate 既有 rows、不重複 header、不補造中斷資料。
- [x] Recorder process 仍存活與 process 已結束需採用安全的各自恢復路徑，但都遵守同一 300 秒限制。
- [x] Resume 前驗證 canonical GPS schema；不合法時拒絕接續並保留原檔案與明確錯誤。
- [x] Backend restart 後可由持久化時間與 GPS 最後可解析 row 恢復 Resume／Timeout 判斷，不把額度重置。
- [x] Resume Timeout 後 AP3 child 維持失敗／不完整，GPS file 若有有效 rows 則 finalize 為 Partial GPS Result。
- [x] AP3 Device Health 後續可恢復 Ready，但不改寫該舊 mission，也不自動建立新 mission。
- [x] Frontend 顯示 Resume Timeout 與 Partial GPS file available；USRP 繼續採樣並維持原 `mission_id`。
- [x] Resume 與 Stop／status 併發時使用既有鎖定與原子寫入，不會在 Stop 後重新啟動 recorder。

## Comments

- 新增 `CaptureCoordinator.resume_uav` 公開 AP3 Capture Resume seam；`record_gps_sample` 在 Bound Mission 的 reconciling child 收到 recovery sample 時自動沿用原 mission/path，status poll 也可用持久化 deadline 在 backend restart 後完成 resume 或 timeout 判斷。
- Resume 先驗證 canonical GPS schema，再依 300 秒 inclusive boundary 分流；存活 recorder 沿用 process，死亡 recorder 以同一 mission 重新 launch（既有 recorder append 開檔），逾時則終止 AP3、保留有效 rows 為 `file=ready` 的 Partial GPS Result 與 `phase=resume_timeout`，不改 USRP child。
- 新增 `/api/capture/uav/resume` route 與 USRPTelemetry 的 `GPS RESUME TIMEOUT`／`Partial GPS file available.` 文案；測試涵蓋 299、300、301 秒、schema rejection、append/header、process death/restart、USRP isolation 與 stop race。
- Code review 後將 sync sample 的 eligibility 判斷與 append 收進 coordinator lock：超過期限或 Stop 後的 recovery row 不會寫入 CSV/log 或 broadcast；recorder 也共用同一 inclusive deadline helper，exit code 2 會在 status 明確結算為 Resume Timeout 與 Partial GPS Result。
- 驗證：`frontend` USRPTelemetry Vitest 32/32、`npm run build`、Python 3.11 `py_compile` 與 `git diff --check` 通過。Backend unittest 無法執行：repo launcher 指向失效 Python 3.12；Python 3.11 以 repo site-packages 執行時缺少相容的 `pydantic_core._pydantic_core` binary（`ModuleNotFoundError`）。
- 完整 frontend Vitest 為 160/161；唯一失敗是未修改的 `SimulationPanel.test.tsx` mock response 缺少 `text()`，收到 `response.text is not a function`。獨立 AP3 recorder 300/301 邊界 unittest 1/1 通過；其餘 backend runtime tests 仍受上述 Python 環境阻礙。
