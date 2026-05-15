# Integrated Sim World

整合即時 GPS、3D 場景、地圖選點建模（Blender + blosm）、照片上傳、Sionna 模擬。

## 目前功能

### 前端
- 即時 GPS 追蹤（WebSocket）
- 多裝置顯示與切換
- 3D UAV 場景檢視（NTPU / NYCU / 生成場景）
- 地圖選點頁（my_map）：
  - 可自由平移、自由縮放瀏覽
  - 建模時固定使用 zoom 17
  - 點選中心點後送出 Blender 任務
  - 成功後回到 React 主頁
- 照片上傳與歷史查看
- Sionna 視覺化圖層查看
- ALIGN AP3 / M4P TOP 無人機即時定位顯示

### 後端
- FastAPI REST + WebSocket (`/ws/gps`)
- 場景任務 API：
  - `POST /api/location/select`
  - `POST /api/scene-tasks/from-location`
  - `GET /api/scene-tasks`
  - `GET /api/scene-tasks/{task_id}`
  - `GET /api/scene-tasks/{task_id}/metadata`
  - `POST /api/scene-tasks/{task_id}/run`
- Blender 任務狀態自動校正（避免 artifact 已生成但狀態仍 running）
- zoom 固定策略：建立任務時後端強制 `zoom=17`
- AP3 MAVLink bridge：透過 USB ADB forward 接無人機資料到 `/ws/gps`

### Blender / blosm 生成策略（目前）
- 以地圖點選座標為中心建模
- 使用 strict zoom bbox（依 zoom 對應範圍）
- 底圖大小可透過 padding 放大（目前已放大）
- 單張 bbox 底圖輸出，避免分塊拼接痕跡
- 可偵測並清除自然圖層殘留（如 water/lake/forest/vegetation）
- 生成 metadata 供檢查：`basemap_*`、`bbox_*`、`excluded_layer_*`
- 已修正 Blender 5.0 與 blosm 相容性問題，優先使用 Blender 4.2 LTS
- 目前預設採用 blosm `3Dsimple`，穩定輸出含建築幾何的 OSM 場景

## 專案結構

- `frontend/`: Vite + React + Three.js
- `backend/`: FastAPI + Blender 任務調度
- `backend/app/blender_generate_scene.py`: Blender 建模與底圖生成腳本
- `tools/ap3_to_simulator.py`: ALIGN AP3 MAVLink -> 模擬器 WebSocket bridge
- `tools/platform-tools/`: Android platform-tools / adb，本機安裝後使用
- `start.ps1`: Windows 一鍵啟動
- `start.sh`: Linux/macOS 啟動

## 安裝需求

- Python 3.12+
- PyTorch 2.9+（Sionna 2.x PHY/SYS 使用 PyTorch）
- Node.js 18+（建議 20+）
- Blender 4.2 LTS，或能相容 blosm 的版本
- Blosm (Blender 插件)
- Mitsuba (Blender 插件)
- （選用）LLVM：Sionna 在 Windows 可能需要 `LLVM-C.dll`
- （選用）cloudflared：若要開外網 tunnel
- Android platform-tools / ADB：若要啟用 AP3 telemetry bridge

## 安裝步驟

### 1) 下載專案

```bash
git clone https://github.com/711483135/integrated-sim-world.git
cd integrated-sim-world
```

### 2) 安裝後端依賴

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\python -m pip install --upgrade pip
.\.venv\Scripts\python -m pip install -r requirements.txt
cd ..
```

### 3) 安裝前端依賴

```powershell
cd frontend
npm install
cd ..
```

### 4) 準備前端環境檔

```powershell
cd frontend
if (Test-Path .env.example) { Copy-Item .env.example .env -Force }
cd ..
```

### 5) 安裝 Blender 與插件

Blender 版本支援 5.1/4.1/4.3/4.0/3.6。
安裝成功後，下一步安裝兩個插件：
1. Blosm: https://prochitecture.gumroad.com/l/blender-osm
2. Mitsuba: https://github.com/mitsuba-renderer/mitsuba-blender

兩個插件都安裝成功後，自動生成地圖功能才可以正常使用。

### 6) 安裝 LLVM（Sionna RT / Dr.Jit 需要）

Windows 執行 Sionna RT 時需要 `LLVM-C.dll`。建議用 winget 安裝：

```powershell
winget install --id LLVM.LLVM --exact --accept-package-agreements --accept-source-agreements
```

安裝後確認 DLL 存在：

```powershell
### 7) 部署 ISS_UNET 模型權重 (ISS / Jammer 重建功能)

ISS_UNET 功能需要預訓練的模型權重檔案。請手動將權重檔案放置於後端指定目錄：

1. 建立目錄：`backend/app/model_artifacts/`
2. 將 `best_iss_reconstruction_model.pth` 檔案放入該目錄中。

檔案結構應如下：
```text
backend/app/model_artifacts/
└── best_iss_reconstruction_model.pth
```

若缺少此檔案，系統仍可啟動，但 ISS 重建功能將會顯示錯誤訊息。

## 啟動方式

### Windows（建議）

本機模式（不開 tunnel）

```powershell
.\start.ps1 -NoTunnel
```

含 tunnel

```powershell
.\start.ps1
```

啟動後：
- Frontend: http://localhost:5173
- Backend: http://localhost:8888
- Backend docs: http://localhost:8888/docs
- Public frontend: https://frontend.simworld.website
- Public backend: https://backend.simworld.website

### Linux / macOS

```bash
bash start.sh --no-tunnel
# 或
bash start.sh
```

### 不啟動 AP3 bridge

```powershell
.\start.ps1 -NoAP3
```

## AP3 / M4P TOP USB 連線流程

1. 遙控器用 USB 接到電腦。
2. 遙控器上允許 USB debugging / ADB 授權。
3. 確認 ADB 看得到裝置：

```powershell
.\tools\platform-tools\adb.exe devices
```

應該要看到類似：

```text
xxxxxxxx	device
```

4. 啟動專案：

```powershell
.\start.ps1
```

5. 檢查後端是否收到無人機資料：

```powershell
Invoke-RestMethod http://127.0.0.1:8888/api/gps/devices | ConvertTo-Json -Depth 5
```

## 手動重啟 AP3 bridge

如果 backend 重啟後無人機資料消失，可以手動重建 ADB forward 並重啟 bridge：

```powershell
.\tools\platform-tools\adb.exe forward tcp:15760 tcp:5760

$py = (Resolve-Path backend\.venv\Scripts\python.exe).Path
$script = (Resolve-Path tools\ap3_to_simulator.py).Path
$logDir = (Resolve-Path .logs).Path

Start-Process -FilePath $py `
  -ArgumentList @("-u", $script, "--websocket-url", "ws://127.0.0.1:8888/ws/gps") `
  -WorkingDirectory (Resolve-Path .).Path `
  -RedirectStandardOutput ($logDir + "\ap3_bridge.log") `
  -RedirectStandardError ($logDir + "\ap3_bridge.log.err")
```

## 實際操作流程（地圖建模）

1. 開啟 `http://localhost:5173`
2. 進入地圖選點頁（my_map）
3. 自由移動/縮放找到目標區域
4. 點選中心點
5. 按「送出 Blender 任務並返回 React」
6. 系統建立場景任務（後端固定 zoom=17）
7. 回到 React 後等待任務完成並查看生成場景

## 常用 API 測試

```powershell
Invoke-RestMethod http://127.0.0.1:8888/ping
Invoke-RestMethod http://127.0.0.1:8888/api/scene-tasks | ConvertTo-Json -Depth 6
Invoke-RestMethod http://127.0.0.1:8888/api/scene-tasks/<task_id> | ConvertTo-Json -Depth 8
Invoke-RestMethod http://127.0.0.1:8888/api/scene-tasks/<task_id>/metadata | ConvertTo-Json -Depth 8
```

## 任務與輸出檔案

每個任務輸出在：

- `backend/app/static/scenes/generated/<task_id>/scene.glb`
- `backend/app/static/scenes/generated/<task_id>/scene.blend`
- `backend/app/static/scenes/generated/<task_id>/scene_metadata.json`
- `backend/app/static/scenes/generated/<task_id>/blender_stdout.log`
- `backend/app/static/scenes/generated/<task_id>/blender_stderr.log`

## 常見問題

### 1) 顯示 running 很久，像是卡住
- 先打 `GET /api/scene-tasks/{task_id}`，系統會嘗試用 artifact 自動校正狀態
- 再看 `scene_metadata.json` 是否已是 completed
- 再看 `blender_stderr.log` 是否有錯誤

### 2) `start.ps1` 啟動失敗
- 確認 Python venv 存在：`backend/.venv`
- 確認前端依賴存在：`frontend/node_modules`
- 先清掉占用 port 5173 / 8888 的程序再重啟

### 3) 生成範圍/底圖大小不符預期
- 查看該 task 的 metadata：
  - `bbox_mode`
  - `bbox_span_tiles`
  - `basemap_cover_padding`
  - `basemap_applied_size`

### 4) blosm 沒有建築物
- 優先確認是否使用 Blender 4.2 LTS
- Blender 5.0 可能因為 `bgl` 缺失導致 blosm addon 失敗
- 目前專案使用 `3Dsimple`，會有 OSM 建築幾何，但不是 realistic 材質建築
- 如果要 realistic，需要另外安裝 blosm assets pack

## 目前開發重點

- 生成場景視覺對齊與品質微調
- 任務狀態與使用者等待體驗
- Blender/blosm 物件過濾與場景清理策略
