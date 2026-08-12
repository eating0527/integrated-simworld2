# 04 — 完成 Bound Start 第一階段 Release

**What to build:** 讓操作人員只有在 AP3 與 RasPi 都 Ready 時才能建立綁定任務；成功時兩個 child 共用同一個 `mission_id`，建立任務後若任一 child 啟動失敗，另一側繼續採樣並呈現 Degraded。此 ticket 完成 WF1–WF3 的第一階段 release gate。

**Blocked by:** 03 — 分離 Device Health 與 Mission Child State.

**Status:** ready-for-agent

- [ ] Bound Start 在建立 mission 前完成 AP3 與 RasPi／USRP preflight。
- [ ] 任一 preflight 失敗時不建立 mission、不啟動任何 child，response 與前端明確指出 AP3、Raspberry Pi 或兩者不可用。
- [ ] Both Ready 時只建立一個 mission，mission、AP3 child 與 USRP child 的 `mission_id` 完全一致，且在 launch 前已持久化。
- [ ] AP3 啟動成功、USRP 啟動失敗時，AP3 繼續、USRP Failed、Mission Degraded。
- [ ] USRP 啟動成功、AP3 啟動失敗時，USRP 繼續、AP3 Failed、Mission Degraded。
- [ ] 單邊啟動失敗不 rollback、stop 或重建另一邊，也不產生第二個 mission。
- [ ] Bind 關閉時仍可獨立啟動符合 Health 與衝突條件的 AP3 或 USRP。
- [ ] 任一 child active 或停止／收尾未解決時，Bind 與 Test／USRP mode 不可切換。
- [ ] Backend、API 與 Frontend integration tests 覆蓋所有 preflight、shared mission、one-sided failure 與控制鎖定情境。
- [ ] 第一階段相關 Backend tests、Frontend tests 與 production build 全部通過後，才可視為 release gate 完成。
