# 02 — 建立 Mission State Contract 與前端狀態摘要

**What to build:** 讓 Backend 與 Frontend 共用一套可判斷整個綁定任務生命週期的狀態契約。前端直接依 Mission Overall State 顯示任務，不再以任一服務是否 Active 推測 Ready，並從任務子狀態補上 GPS／Noise 的具體失敗原因。

**Blocked by:** None — can start immediately.

**Status:** ready-for-agent

- [ ] 外部 Mission Overall State 支援 Ready、Starting、Running、Degraded、Stopping、Finalizing、Completed、Completed with Warning 與 Failed。
- [ ] 外部契約不再回傳 Partial Failed；既有持久化資料若仍含舊值，載入後能安全轉換為正確的新狀態而不遺失任務。
- [ ] 聚合測試涵蓋雙邊 Running、任一邊失敗仍 Degraded、雙邊失敗、Stopping、Upload Pending／Finalizing、Completed，以及 GPS／Noise 各自失敗的 Completed with Warning。
- [ ] Upload Pending 不會聚合成 Completed 或 Completed with Warning；Presumed running 不會被視為 Stopped。
- [ ] Frontend mission badge 直接使用 Overall State，全部 Failed 時不得顯示 Ready。
- [ ] Degraded 畫面明示 `GPS/NOISE FAILED/OFFLINE`，並顯示另一側仍在進行的動作。
- [ ] Completed with Warning 畫面明示 `GPS FAILED` 或 `NOISE FAILED`。
- [ ] AP3 與 USRP 區塊各自顯示 Connection、Service、File、Phase 與 Error；未知 response value 不會降級成 Ready。
- [ ] Backend state、API response、Frontend type 與元件測試同步更新。
