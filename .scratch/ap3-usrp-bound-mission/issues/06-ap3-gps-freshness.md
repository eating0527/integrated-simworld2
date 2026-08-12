# 06 — 偵測 AP3 GPS Freshness 中斷

**What to build:** 綁定任務進行時，系統同時考量本機 recorder process、AP3 連線與最後有效 GPS 時間；即使 recorder process 仍活著，只要 GPS 已停止更新，Frontend 就會顯示 GPS Offline 與 Mission Degraded，而 USRP 繼續採樣。

**Blocked by:** 04 — 完成 Bound Start 第一階段 Release.

**Status:** ready-for-human

- [x] 每次成功寫入有效 GPS 後，任務持久化資料能反映可供監控使用的 last sample time。
- [x] Runtime status 不再只以 recorder process 存活判定 AP3 Running。
- [x] AP3 連線中斷或 GPS 超過 freshness threshold 未更新時，AP3 child 進入可恢復的異常／reconciling 狀態，Mission 顯示 Degraded。
- [x] AP3 異常時 USRP 保持原 service、file 與 `mission_id`，不被停止或重建。
- [x] 斷線時間與 resume deadline 以任務狀態持久化，供後續 AP3 Capture Resume 使用。
- [x] Frontend 顯示 GPS Offline／失去新資料及 Noise 仍 Recording，而不是把整個任務顯示 Failed 或 Ready。
- [x] Recorder process 已死亡、仍存活但無資料、ADB Offline 與正常 fresh sample 可被測試區分。
- [x] Status、freshness 更新與既有 capture state 原子寫入不會互相覆蓋。

## Comments

- `ChildState` 新增 `last_sample_at`、`disconnected_at`、`resume_deadline_at`，並由 `CaptureCoordinator.record_gps_sample` 在 GPS sync 成功後以既有鎖定／原子寫入持久化。
- Runtime status 同時檢查 recorder process、AP3 health 與 canonical GPS CSV 的最新可解析 timestamp；超過 10 秒進入 `presumed_running`／`reconciling`，不因程序仍存活而誤報正常 Running。
- `resume_deadline_at` 以最後有效 GPS sample（無 sample 時以 `started_at`）加 300 秒計算，供後續 AP3 Capture Resume 使用；本 ticket 不執行 deadline expiry、resume 或 partial-result 結算。
- Bound Mission freshness 測試確認 USRP service、file 與 `mission_id` 不因 AP3 stale 改變；GPS fresh sample 與 live process 維持 Running，程序死亡則明確為 failed phase。
- Telemetry 顯示 `DEGRADED · GPS OFFLINE · NOISE RECORDING` 與 Last GPS sample，不加入後續 Resume／Partial GPS UI。
- 驗證：`USRPTelemetry` Vitest 31/31、frontend production build 通過；backend Python launcher（repo `.venv` 與系統 `python`）目前無法啟動，新增 `Ap3FreshnessTests` 尚待主代理在可用 Python 環境執行。
