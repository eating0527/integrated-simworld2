# 03 — 乾淨面板、任務摘要與重新載入恢復

**What to build:** Control Mode 切換後呈現乾淨控制面板而不誤顯示舊任務狀態；未結案任務在前端重新載入時恢復可操作畫面。GPS 與 Noise 分別顯示上次任務開始時間和 mission ID 後五碼；Bound 任務在兩區各自顯示相同摘要；任務與 RasPi 現有時間都以台北時區的 `MM/DD HH:mm:ss` 顯示，且不改變後端紀錄格式或 RasPi 時間語意。

**Blocked by:** 02 — Control Mode 守門與任務所有權.

**Status:** ready-for-human

- [x] 無未結案任務時預設 Independent，並顯示乾淨面板：保留目前 Device Health 與可用的 idle controls，不重現終態任務的 phase、檔案、錯誤或 retry action。
- [x] 重新載入前端後，未結案的 Bound 或 Independent GPS／Noise 任務會回到相應的控制模式並保有可操作控制；終態任務不會被恢復成目前控制狀態。
- [x] 每個服務在兩種乾淨面板中都顯示最近一筆涉及該服務的任務開始時間與 `#` 加 mission ID 後五碼；無歷史則顯示 `—`，Bound 任務在 GPS 與 Noise 區顯示同一摘要。
- [x] 任務摘要時間與既有 RasPi health 時間皆只在前端以 Asia/Taipei 的 `MM/DD HH:mm:ss` 格式呈現，不修改後端欄位、值或 RasPi 時間意義。
- [x] 加入狀態投影、面板、重新載入、歷史摘要與可及性提示的前後端回歸測試，並完成完整驗證。

## Comments

- 後端 status payload 新增 `control_mode`、僅含未結案任務的 `active` 投影，以及跨模式每服務最新任務的 `history` 摘要；終態紀錄仍保留於 `capture.json`。
- 前端以投影決定 reload 恢復或 clean idle panel，摘要與 Device Health 時間統一以 Asia/Taipei `MM/DD HH:mm:ss` 顯示，缺少歷史顯示 `—`。
- 驗證：後端 294 tests、前端 180 tests、frontend production build 均通過。
