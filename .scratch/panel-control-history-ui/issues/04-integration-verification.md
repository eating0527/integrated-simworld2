# 04 — 整合驗收與原型清理

**What to build:** 讓正式的 B 版型在目標瀏覽器與筆電 viewport 中通過行為及視覺驗收，並移除僅供決策的 DEV prototype。

**Blocked by:** 02 — 採樣控制資訊階層; 03 — Historical Mission List 與套用摘要.

**Status:** ready-for-agent

- [ ] 移除或移出正式工作樹中的 DEV-only prototype 與其 gate，不把 throwaway 靜態資料帶入產品。
- [ ] 受影響的採樣控制、Historical Mission List 與 Workspace 行為測試通過。
- [ ] Chrome 與 Brave 在 1280×800、1164×727、1536×864、1920×1080 驗收無水平捲軸、必要資訊未截斷，且側欄模式符合規格。
- [ ] 前端 production build 通過。
