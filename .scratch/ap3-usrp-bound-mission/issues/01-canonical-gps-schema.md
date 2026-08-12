# 01 — 統一 GPS CSV Schema

**What to build:** 建立一個可被 GPS 建立、採樣 append、停止驗證與後續讀取共同遵循的 canonical schema，使同一任務的 GPS 檔案不再因不同模組使用四欄或五欄格式而在收尾時失敗。這是 AP3 採樣接續的前置整理；完成後現有採樣與停止流程仍維持原行為。

**Blocked by:** None — can start immediately.

**Status:** ready-for-agent

- [ ] 新建立的 GPS 檔案固定使用 `time_stamp、lat、lon、alt、alt_mode` 的欄位與順序。
- [ ] Recorder append、Coordinator 建檔、停止驗證、GPS 同步寫入及消費端不再各自維護互相矛盾的 header。
- [ ] 對已存在且 schema 正確的 GPS 檔案執行 append 時，不清空既有資料，也不重複寫入 header。
- [ ] Schema 不合法時回報明確錯誤，不繼續 append 或把任務誤標成成功完成。
- [ ] 既有 GPS timestamp 與 altitude mode 行為維持相容。
- [ ] 自動測試涵蓋建檔、append、停止驗證、錯誤 schema 與既有檔案不被覆寫。
