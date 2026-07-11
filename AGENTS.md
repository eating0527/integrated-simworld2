# Repository Guidelines

## Project Structure & Module Organization

- `frontend/` is the React/Vite client: UI in `src/components/`, effects in `src/hooks/`, and helpers in `src/utils/`.
- `backend/app/` is the FastAPI and simulation service; backend tests are in `backend/tests/`.
- Frontend tests are in `frontend/tests/` or colocated as `*.test.tsx`. Operational and conversion scripts live in `tools/`.
- Put generated assets under `backend/app/static/` or `frontend/public/`, never in source folders.

## Project Invariants

- `App` 組合跨區域狀態；展示元件優先透過 props 接收資料，瀏覽器、GPS 與 WebSocket 副作用放在 hooks。
- 裝置狀態統一使用 `frontend/src/store/useDeviceStore.ts`；不要在元件內建立第二份來源。
- GPS 與 3D 座標轉換統一重用 `frontend/src/utils/geo.ts`；修改轉換時同步更新雙向轉換與測試。
- API 使用 `VITE_API_URL`，WebSocket 使用 `VITE_WS_URL`；不要硬編碼環境網址。

## Frontend Guidelines

- 維持深色、半透明、技術監控風格與既有 CSS 變數；不要任意新增顏色系統或重複元件。
- 桌面側欄寬度維持 `clamp(292px, 23vw, 360px)`；`1099px` 以下使用抽屜式側欄。
- `1320px` 與 `600px` 是狀態列的響應式斷點；元件不可造成水平捲軸。
- `Workspace` 內的子元件必須可縮小：`width: 100%`、`min-width: 0`、`max-width: 100%`。
- 優先重用 `MinPanel`；收合面板不得推擠 3D 主場景，浮動選單不得改變主要版面尺寸。
- 互動元件保留鍵盤 focus、`aria-expanded`、`aria-controls`、Escape 關閉與足夠的觸控尺寸。
- 修改 API response 或 WebSocket event 時，同步更新前端型別、事件處理與測試。

## Backend Guidelines

- Route handler 只做輸入驗證、呼叫 service/coordinator 與格式化回應。
- 任務控制優先使用 `CaptureCoordinator`；硬體控制使用 `usrp_ctl.py`；模擬與 ISS-UNet 使用既有 service。
- 不在 `main.py` 新增重複的任務、硬體或模擬邏輯；既有程式只有在修改相關流程時才逐步拆分。
- ADB、SSH、Blender、Overpass、Sionna 等阻塞工作使用 `asyncio.to_thread` 或背景工作，並設定 timeout。
- 外部硬體或服務不可用時回傳明確錯誤，不得讓整個 API 啟動失敗。

## Domain Contracts

- GPS WebSocket 事件維持 `register-device`、GPS payload、`clear-path`、`photo-upload`、`photo_deleted` 與 `device-disconnected`。
- GPS payload 至少包含 `deviceId`、`deviceName`、`lat`、`lon`、`alt`、`accuracy` 與 `timestamp`。
- `capture.json` 是任務狀態的持久化來源；UAV 與 USRP 分開呈現 connection、service、file 狀態。
- USRP 停止後，檔案完成上傳前不得回報 `completed`；上傳失敗保留 `upload_pending`。
- SSH 中斷時保留 `presumed_running`，不可擅自送出 stop 或 restart。
- 執行中的任務不可切換 Bind 或 Test/USRP 模式。
- 任務狀態更新需使用既有鎖定與原子寫入，避免並行請求破壞 `capture.json`。

## Security & Data Files

- 所有上傳檔案限制大小、驗證格式並清理檔名；禁止路徑穿越與任意檔案刪除。
- SSH 密碼與裝置設定只能來自環境變數；不可寫入程式碼、log 或 API response。
- Shell command 必須安全 quoting，不直接拼接未驗證輸入。
- 生成的 scene、map、log、CSV 與模型輸出不可混入原始碼或提交到 Git。

## Build, Test, and Development Commands

- `.\start.ps1 -NoTunnel` starts the backend on `:8888` and Vite on `:5173`; add `-Reload` for backend auto-reload.
- `cd frontend; npm run dev` runs the client; `npm test` runs Vitest; `npm run build` type-checks and bundles it.
- `cd backend; .\.venv\Scripts\python -m unittest discover -s tests` runs backend tests.
- `python tools\test_pi_radio_stack.py` checks the Raspberry Pi radio-stack integration when that hardware is available.

## Coding Style & Naming Conventions

Use two spaces in TypeScript/TSX and four in Python. Components use PascalCase (`GPSStatus.tsx`), hooks `useThing.ts`, helpers camelCase, and Python `snake_case`. Name tests `test_<behavior>.py` or `<Component>.test.tsx`. No formatter or linter is configured; match the edited file.

## Testing Guidelines

Add the smallest relevant regression test. Frontend tests use Vitest/jsdom and backend tests use `unittest`. Run the affected suite, then `npm run build` for frontend changes. Avoid hardware-dependent tests unless changing that integration.

## Commit & Pull Request Guidelines

Recent history uses Conventional Commit-style subjects, such as `feat(ui): add status summaries`. Keep commits focused and imperative. PRs need the user-visible change, tests run, linked issue (if any), and UI screenshots. Never commit secrets, logs, or large derived output.

## Git Ignore Rules

Keep secrets in `.env` or `frontend/.env.local`. Existing rules already ignore dependencies, caches, logs, temporary files, mission captures, and generated models or scenes.

- Level 1 永遠忽略：secrets、`.env*`（`.env.example` 除外）、dependency 安裝環境、IDE/local agent 個人設定、模型權重與本機工具安裝。
- Level 2 忽略並定期清理：logs、build、cache、test tmp、runtime mission、生成圖/地圖/場景與可重建索引；清理前先停止服務。
- Level 3 納入版本控制：source、tests、docs/specs、lockfiles/manifests、example configs、operational scripts、刻意保留 fixtures 與 canonical assets。

`.gitignore` 只影響未追蹤檔；既有 tracked 的 Level 1/2 檔案仍需另用 `git rm --cached <path>` 移出 index，本次規則不會自動修改 staging。