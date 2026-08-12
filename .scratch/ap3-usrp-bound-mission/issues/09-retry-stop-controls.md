# 09 — 覆用 Child Stop 提供 Retry Stop

**What to build:** Stop All 後若只有一邊未能確認停止，Frontend 直接覆用該 child 現有 Stop 按鈕顯示 Retry Stop；已成功的一側顯示 Disabled 的 Stopped。Retry 只作用於失敗 child，不提供 Force Complete 或把未知遠端狀態強制改成本機完成。

**Blocked by:** 08 — 實作並行 Best-Effort Stop All.

**Status:** ready-for-agent

- [ ] Child phase 能區分 stop-failed、一般 failed 與 reconciling，只有可安全重試停止的狀態提供 Retry Stop。
- [ ] 首次 Stop All 後停用 Stop All，避免它與個別 Retry Stop 形成兩個重送入口。
- [ ] 成功停止的 child 顯示 Disabled 的 Stopped，不會再次收到 stop command。
- [ ] Stop 失敗或停止結果不確定的 child 使用原按鈕位置顯示 Retry Stop，並帶入原 `mission_id`。
- [ ] AP3 Retry Stop 只停止 AP3；USRP Retry Stop 只停止 USRP，任何一個都不改動 sibling 的完成狀態。
- [ ] RasPi Offline 時 USRP Retry Stop Disabled，並顯示需等待 Raspberry Pi 重連；Device Health 恢復後自動啟用。
- [ ] Retry Stop 成功後 child 進入 Stopped 並重新聚合 Mission；失敗時維持可重試狀態與 child error。
- [ ] 一般 launch failure 若不存在仍需停止的程序，不會錯誤提供 Retry Stop。
- [ ] UI 保留 keyboard focus、Disabled 語意與可讀 error announcement；測試涵蓋 AP3／USRP 各自成功、失敗、離線與恢復。
- [ ] 系統沒有 Force Complete 或只改本機 state 的危險替代操作。
