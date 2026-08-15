# 02 — 採樣控制資訊階層

**What to build:** 讓操作者在採樣控制中清楚區分 Control Mode、裝置就緒、任務狀態與可執行操作，並在窄欄安全地維持關鍵訊息可見。

**Blocked by:** None — can start immediately.

**Status:** ready-for-agent

- [ ] Control Mode 固定可見，使用「獨立採樣模式」與「綁定任務模式」，並正確呈現未收尾任務的既有阻擋契約。
- [ ] Independent Capture 提供各自的 GPS 採樣與 Noise 採樣 Start／Stop；Bound Mission 只提供開始或停止綁定任務的共同控制。
- [ ] 分開呈現「裝置就緒」與「任務狀態」；停用控制、錯誤與群組化進度提供可讀且可操作的回饋。
- [ ] GPS 顯示準備、錄製、收尾；Noise 顯示連線與設定、錄製、收尾與上傳，並保留完整 Phase 作為詳細狀態。
- [ ] 錯誤顯示在所屬 GPS 或 Noise 區塊；只有共同錯誤可出現在面板標頭。
- [ ] 中文操作文案遵守「動詞＋明確對象」，USRP 僅作硬體或模式名稱，使用者操作名稱為 Noise 採樣。
- [ ] 窄欄收合上次任務、最後 GPS 與完整步驟，但保留 Connection、Phase、File、錯誤與模式切換阻擋。
