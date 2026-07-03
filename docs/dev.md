# 開發筆記

這份文件放目前開發重點與維護注意事項。

## 目前開發重點

- 生成場景視覺對齊與品質微調。
- `建模選點` 到 React 主畫面的等待體驗。
- Blender/blosm 物件過濾與場景清理策略。
- `採樣控制面板` 的 GPS / Noise 任務狀態一致性。
- `Noise with GPS` 的 CSV 對齊與統計圖輸出。

## 維護原則

- README 只保留 production、安裝與前端操作。
- 後端、硬體、API、測試與技術細節放在 `docs/`。
- 操作文件優先使用畫面上實際看到的文字，例如 `送出 Blender 任務並返回 React`、`Start USRP`、`開始計算`。
- 機密只放本機 `.env`，不要寫進文件、前端環境檔或 commit。

## 文件分工

- `docs/ops.md`: 後端、AP3、Raspberry Pi、USRP、Cloudflare tunnel。
- `docs/tech.md`: API、Blender、Sionna、ISS_UNET、輸出檔。
- `docs/test.md`: 測試、smoke test、啟動檢查。
- `docs/dev.md`: 開發重點與文件維護規則。
