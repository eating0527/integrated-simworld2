# 02 — 採樣控制資訊階層

**What to build:** 讓操作者在採樣控制中清楚區分 Control Mode、裝置就緒、任務狀態與可執行操作，並在窄欄安全地維持關鍵訊息可見。

**Blocked by:** 01 — 1200px 側欄抽屜行為.

**Status:** ready-for-agent

- [ ] Control Mode 固定可見，正確呈現 Independent Capture 與 Bound Mission 的既有阻擋契約。
- [ ] Independent Capture 提供各自的 GPS 採樣與 Noise 採樣控制；Bound Mission 只提供綁定任務共同控制。
- [ ] 分開呈現裝置就緒與任務狀態；停用控制、錯誤與群組化進度提供可操作且可讀的回饋。
- [ ] 中文操作文案遵守「動詞＋明確對象」，且 USRP 僅作硬體或模式名稱。
- [ ] 窄欄收合非即時診斷資訊，但保留 Connection、Phase、File、錯誤與模式切換阻擋。
