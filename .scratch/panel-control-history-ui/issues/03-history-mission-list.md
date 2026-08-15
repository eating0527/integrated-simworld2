# 03 — Historical Mission List 與套用摘要

**What to build:** 讓操作者在 Historical Mission List 判讀並選取 Mission Bundle，區分 GPS／Noise artifact 的可用性與 GPS 軌跡預覽，且只在明確操作後套用資料到模擬。

**Blocked by:** None — can start immediately.

**Status:** ready-for-agent

- [ ] Historical Mission List 只呈現 Mission Bundle，不混入 Bound Mission 或 Independent Capture 的 live 狀態。
- [ ] 每個 Mission Bundle 以 `mission_id`、`updated_at` 與 GPS／Noise artifact 狀態呈現；Healthy Artifact、Invalid Artifact 與缺少 artifact 有明確區別。
- [ ] Mission Selection 與 GPS 軌跡預覽中分開呈現；只有 Noise artifact 的 Mission Bundle 仍可選取與套用。
- [ ] 只套用 Healthy Artifact；缺少 artifact 保留現有 Simulation Panel CSV，且不改變 Simulation Mode。
- [ ] Historical Mission List 初始收合，僅在成功匯入傳入任務後自動展開；不新增搜尋、篩選或手動排序。
- [ ] 已選取 Mission Bundle 顯示唯一清楚的套用至模擬主操作，並維持後端的最新 `updated_at` 優先排序。
