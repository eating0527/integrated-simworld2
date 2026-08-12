# 06 — 偵測 AP3 GPS Freshness 中斷

**What to build:** 綁定任務進行時，系統同時考量本機 recorder process、AP3 連線與最後有效 GPS 時間；即使 recorder process 仍活著，只要 GPS 已停止更新，Frontend 就會顯示 GPS Offline 與 Mission Degraded，而 USRP 繼續採樣。

**Blocked by:** 04 — 完成 Bound Start 第一階段 Release.

**Status:** ready-for-agent

- [ ] 每次成功寫入有效 GPS 後，任務持久化資料能反映可供監控使用的 last sample time。
- [ ] Runtime status 不再只以 recorder process 存活判定 AP3 Running。
- [ ] AP3 連線中斷或 GPS 超過 freshness threshold 未更新時，AP3 child 進入可恢復的異常／reconciling 狀態，Mission 顯示 Degraded。
- [ ] AP3 異常時 USRP 保持原 service、file 與 `mission_id`，不被停止或重建。
- [ ] 斷線時間與 resume deadline 以任務狀態持久化，供後續 AP3 Capture Resume 使用。
- [ ] Frontend 顯示 GPS Offline／失去新資料及 Noise 仍 Recording，而不是把整個任務顯示 Failed 或 Ready。
- [ ] Recorder process 已死亡、仍存活但無資料、ADB Offline 與正常 fresh sample 可被測試區分。
- [ ] Status、freshness 更新與既有 capture state 原子寫入不會互相覆蓋。
