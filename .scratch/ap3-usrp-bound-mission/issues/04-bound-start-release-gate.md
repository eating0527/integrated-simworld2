# 04 — 完成 Bound Start 第一階段 Release

**What to build:** 讓操作人員只有在 AP3 與 RasPi 都 Ready 時才能建立綁定任務；成功時兩個 child 共用同一個 `mission_id`，建立任務後若任一 child 啟動失敗，另一側繼續採樣並呈現 Degraded。此 ticket 完成 WF1–WF3 的第一階段 release gate。

**Blocked by:** 03 — 分離 Device Health 與 Mission Child State.

**Status:** ready-for-human

- [x] Bound Start 在建立 mission 前完成 AP3 與 RasPi／USRP preflight。
- [x] 任一 preflight 失敗時不建立 mission、不啟動任何 child，response 與前端明確指出 AP3、Raspberry Pi 或兩者不可用。
- [x] Both Ready 時只建立一個 mission，mission、AP3 child 與 USRP child 的 `mission_id` 完全一致，且在 launch 前已持久化。
- [x] AP3 啟動成功、USRP 啟動失敗時，AP3 繼續、USRP Failed、Mission Degraded。
- [x] USRP 啟動成功、AP3 啟動失敗時，USRP 繼續、AP3 Failed、Mission Degraded。
- [x] 單邊啟動失敗不 rollback、stop 或重建另一邊，也不產生第二個 mission。
- [x] Bind 關閉時仍可獨立啟動符合 Health 與衝突條件的 AP3 或 USRP。
- [x] 任一 child active 或停止／收尾未解決時，Bind 與 Test／USRP mode 不可切換。
- [x] Backend、API 與 Frontend integration tests 覆蓋所有 preflight、shared mission、one-sided failure 與控制鎖定情境。
- [x] 第一階段相關 Backend tests、Frontend tests 與 production build 全部通過後，才可視為 release gate 完成。

## Comments

- Bound Start 現在會先完成 AP3 與 Raspberry Pi 的雙 preflight，並以結構化 per-device errors 回報所有不可用裝置；拒絕時不建立 mission 或啟動 child。
- 成功時先持久化單一 shared `mission_id` 再 launch；任一 child launch 失敗只標記該 child，健康 sibling 繼續且 Mission Overall State 為 Degraded。
- Bind、Test／USRP mode 與新任務控制在 active、stopping、finalizing、upload pending、reconciling 或 stop failed 未解決時鎖定；獨立啟動仍依 Device Health 與 conflict gate 運作。
- Review 修正 AP3-only acceptance coverage，並讓 production RasPi preflight 優先使用 lightweight `get_drone_health`；舊 adapter 保留 status fallback 相容層。
- 驗證：backend targeted 74/74、完整 backend 227/227、USRPTelemetry 27/27、frontend production build 通過、`git diff --check` 與 Python compile 通過。完整 frontend 155/156；唯一失敗為既有 `SimulationPanel` 測試 mock 缺少 `response.text()`，與本 ticket 無關且已於 ticket 03 記錄。
