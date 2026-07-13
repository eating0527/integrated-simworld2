# 場景解析度與材質修復設計

## 目標

1. 新場景建模完成後，同時產生 1m、2m、4m 三種 ISS-UNet 資料。
2. 修復 NTPU 與 NYCU 重建場景的材質與底圖，避免全白 3D 或空白底圖。

## 範圍與方案

沿用現有場景建立流程與 `prepare_iss_unet_dataset`。在 Blender 成功後，場景任務協調器依序以 `pixel_size_m=1, 2, 4` 呼叫既有 service；不新增 API 解析度、不新增抽象層。每種解析度使用現有檔名規則，4m 維持既有檔名相容性。

Blender 腳本在入口將輸出目錄解析為絕對路徑，讓底圖檔案、材質載入與 GLB 打包使用同一個可解析路徑。底圖下載失敗時保留既有實色地面 fallback，並保留錯誤 metadata 供診斷。

## 資料流

`scene task` → Blender 建模與材質/底圖 → `prepare_iss_unet_dataset(1m)` → `(2m)` → `(4m)` → 任務完成。

任務回應保留既有 `issUnetDataset` 欄位，並附上三種解析度的結果清單，避免前端既有 4m 使用路徑失效。

## 具體變更

- `backend/app/main.py`：將場景資料準備改為 1/2/4m 依序執行，保留錯誤處理與任務狀態。
- `backend/app/blender_generate_scene.py`：解析 `output-dir` 為絕對路徑；材質、底圖與 GLB 仍使用既有流程。
- `backend/tests/`：加入解析度清單與回傳結果的回歸測試，以及絕對輸出路徑測試。
- 重新生成 `backend/app/static/scenes/NTPU/`、`NYCU/`，成功後同步 GLB 至 `frontend/public/scenes/`。

## 驗證

- 後端場景與 ISS-UNet 測試。
- 檢查兩個場景各有 1m/2m/4m 四組資料檔案（建築高度、DSS、ISS、TSS）。
- 檢查兩個場景 metadata 的底圖狀態與 PNG 存在。
- 檢查 GLB 有有效大小與影像材質引用。
- 前端測試與 `npm run build`。

## 非目標

- 不改前端解析度選項與 API schema。
- 不重構 Blender 材質系統或引入新下載服務。
- 不處理工作樹中既有的 USRP 與地圖檔案修改。
