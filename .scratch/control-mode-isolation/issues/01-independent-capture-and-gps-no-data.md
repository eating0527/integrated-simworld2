# 01 — Independent Capture 與 GPS 無資料容忍

**What to build:** 在 Independent Control Mode 中，GPS 與 Noise 可由不同硬體各自獨立啟動、停止與完成；其中一方的未結案狀態不會鎖住另一方的 START／STOP 或 Noise 的 Test／USRP 模式選擇。健康的 GPS recorder 即使暫時未收到 GPS data 仍維持執行，正常停止後只有 canonical CSV header 的任務也可完成。

**Blocked by:** None — can start immediately.

**Status:** ready-for-human

- [x] Independent 下可在 GPS 執行時啟動、停止 Noise，也可在 Noise 執行、上傳或錯誤時啟動、停止 GPS；每個服務只受自身未結案狀態與自身硬體健康度限制。
- [x] GPS 執行不會鎖住 Noise 的 Test mode 或 USRP mode；Noise 本身未結案時，模式選擇仍依既有 Noise 安全規則處理。
- [x] 移除「超過 10 秒未收到 GPS row 即轉為 Reconciling／Presumed running」；AP3 連線失敗與 recorder process 結束仍保留既有安全處理。
- [x] GPS recorder 正常停止時，僅含 canonical header 的 CSV 視為可完成任務。
- [x] 加入前後端回歸測試，並完成受影響測試、完整後端與前端測試及前端 production build。

## Comments

- 後端 GPS freshness 現改由 AP3 health 與 recorder process ownership 判定；健康但無 GPS rows 的 recorder 維持 Running，AP3 offline 仍進入 Reconciling。
- 前端 Noise Test／USRP 選擇不再因 GPS 未結案而 disabled。
- 驗證：後端 283 tests、前端 169 tests、frontend production build 均通過。
