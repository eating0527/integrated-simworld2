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

## 檔案分級與清理

Level 1 與 Level 2 都不進 Git；Level 3 才納入版本控制。

`.gitignore` 只影響未追蹤檔；既有 tracked 的 Level 1/2 檔案仍需另用 `git rm --cached <path>` 移出 index，本次規則不會自動修改 staging。

| 層級 | 範圍與例子 | Git 規則 | 處理方式 |
| --- | --- | --- | --- |
| Level 1：本機機密與環境 | `**/.env`、`**/.env.*`（`.env.example` 除外）、`node_modules/`、`.venv/`、IDE/代理個人設定、本機工具安裝、`backend/app/model_artifacts/`、`*.pt`、`*.pth` | 永遠忽略 | 機密只留本機；環境與工具需要時重新安裝 |
| Level 2：可重建產物 | logs、`dist/`、`build/`、cache、`__pycache__/`、test tmp、`incoming/mission_*/`、暫存輸出、生成圖/地圖/場景、`backend/app/uploads/scene_index.json` | 忽略 | 停止服務後定期清理；需要時由程式或建置流程重建 |
| Level 3：專案來源 | source、tests、docs/specs、lockfiles/manifests、example configs、operational scripts、刻意保留 fixtures、canonical assets | 不忽略 | 需審查後提交；不可用廣泛規則掩蓋 |

### Level 2 清理時機

- 停止 backend、frontend 與其他相關服務後，才清理正在使用的 runtime 檔案。
- 每次停止服務：刪除 logs、test tmp 與暫存檔；保留仍在分析中的 mission 資料。
- 每週：清理 cache、build 與生成圖/地圖/場景；確認沒有未完成任務後再刪除。
- 每月：檢查長期未使用的 runtime mission 與可重建索引，先保留必要 fixture，再清理其餘資料。

`backend/app/uploads/scene_index.json` 是由 `scene_tasks.json` 與場景檔案重建的快取，不是任務的主要持久化來源。`incoming/<mission-id>/` 是執行期間的 mission 資料；不要把個人任務資料當成測試 fixture 提交。地圖入口只保留 `frontend/public/my_map.html`；根目錄不再放第二份地圖 HTML。歷史計畫與 brainstorm 不參與執行期；長期設計決策保留在 `docs/superpowers/specs/`。

### 新檔案判定

先問四件事：含機密或只屬個人環境就是 Level 1；可由建置、測試或服務重建就是 Level 2；支撐執行、測試、文件、設定契約或產品展示且需共同維護就是 Level 3。無法判定時先不要加入 Git，確認用途後再決定。
