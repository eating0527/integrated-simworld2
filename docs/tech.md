# 技術細節

這份文件放 API、Blender、Sionna、ISS_UNET 與輸出檔案。

## 專案結構

- `frontend/`: Vite + React + Three.js
- `backend/`: FastAPI + Blender 任務調度
- `backend/app/blender_generate_scene.py`: Blender 建模與底圖生成腳本
- `tools/ap3_to_simulator.py`: ALIGN AP3 MAVLink 到 WebSocket bridge
- `tools/ap3_to_gps_csv.py`: AP3 GPS CSV 寫入
- `tools/pi_radio_stack.sh`: Raspberry Pi USRP mission stack
- `start.ps1`: Windows 啟動
- `start.sh`: Linux/macOS 啟動

## 場景任務 API

```text
POST /api/location/select
POST /api/scene-tasks/from-location
GET  /api/scene-tasks
GET  /api/scene-tasks/{task_id}
GET  /api/scene-tasks/{task_id}/metadata
POST /api/scene-tasks/{task_id}/run
```

常用檢查：

```powershell
Invoke-RestMethod http://127.0.0.1:8888/ping
Invoke-RestMethod http://127.0.0.1:8888/api/scene-tasks | ConvertTo-Json -Depth 6
Invoke-RestMethod http://127.0.0.1:8888/api/scene-tasks/<task_id> | ConvertTo-Json -Depth 8
Invoke-RestMethod http://127.0.0.1:8888/api/scene-tasks/<task_id>/metadata | ConvertTo-Json -Depth 8
```

## Blender / blosm 策略

- 以 `建模選點` 地圖點選座標為中心建模。
- `Generation Zoom` 固定顯示 `18 (fixed)`。
- 使用 strict zoom bbox。
- 底圖大小可透過 padding 放大。
- 輸出單張 bbox 底圖，避免分塊拼接痕跡。
- 會偵測並清除自然圖層殘留，例如 water、lake、forest、vegetation。
- metadata 會保留 `basemap_*`、`bbox_*`、`excluded_layer_*`。
- 優先使用 Blender 4.2 LTS。
- 預設採用 blosm `3Dsimple`，穩定輸出 OSM 建築幾何。

任務輸出：

```text
backend/app/static/scenes/generated/<task_id>/scene.glb
backend/app/static/scenes/generated/<task_id>/scene.blend
backend/app/static/scenes/generated/<task_id>/scene_metadata.json
backend/app/static/scenes/generated/<task_id>/blender_stdout.log
backend/app/static/scenes/generated/<task_id>/blender_stderr.log
```

## Sionna / ISS_UNET

必要套件在 `backend/requirements.txt`：

```text
sionna==2.0.1
sionna-rt==2.0.1
torch>=2.9.0
```

Windows 需要 LLVM：

```text
C:\Program Files\LLVM\bin\LLVM-C.dll
```

模型權重放在：

```text
backend/app/model_artifacts/best_iss_reconstruction_model.pth
backend/app/model_artifacts/unet_single/best_model.pt
```

前端 `無線通道模擬` 會使用：

- `Sim`
- `GPS`
- `Noise with GPS`
- `OS-CFAR`
- `Building Mask`
- `3D Heatmap Overlay`
- `Overlay Opacity`

`Noise with GPS` 需要：

```text
incoming/<mission-id>/gps.csv
incoming/<mission-id>/noise.csv
```

## 常見技術問題

`running` 很久：

- 先查 `GET /api/scene-tasks/{task_id}`。
- 看 `scene_metadata.json` 是否 completed。
- 看 `blender_stderr.log` 是否有錯。

底圖範圍不符：

- 看 metadata 的 `bbox_mode`、`bbox_span_tiles`、`basemap_cover_padding`、`basemap_applied_size`。

blosm 沒有建築物：

- 優先確認 Blender 4.2 LTS。
- Blender 5.0 可能因為 `bgl` 缺失導致 blosm addon 失敗。
- `3Dsimple` 有 OSM 建築幾何，但不是 realistic 材質建築。
- realistic 需要另外安裝 blosm assets pack。
