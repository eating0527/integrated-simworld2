# 統一 Local ENU 座標框架設計

## 目標

將 GPS、前端 3D、後端建模檔、Sionna、ISS-UNet、CFAR 與 GPS 路線重播統一到以場景中心為原點的 Local ENU 座標，讓任意 GPS 場景都能使用同一套轉換規則。NTPU 與 NYCU 只保留為可選場景，不再作為 baseline 或 fallback。

## 已確認的產品規則

- 每個場景的水平有效範圍固定為 `512m × 512m`。
- Scene origin 位於有效範圍中心：`E,N ∈ [-256, 256]m`。
- 超出建模範圍的 mesh 與地圖資料裁切；不自動擴張或依實際 mesh 尺寸縮放。
- GPS / replay 點可在地圖外顯示最多 `32m`：顯示範圍為 `[-288, 288]m`。
- 超出顯示範圍的點保留原始資料，標記 `out_of_frame=true`，不夾到邊界且不顯示在 3D 場景。
- GPS replay 使用每一筆資料的高度，不再忽略 CSV `alt` 或沿用起始點高度。
- `alt_mode=amsl` 時：`U = alt - origin.alt_m`。
- `alt_mode=relative` 時：`U = alt`。
- 沒有 `alt_mode` 的舊 CSV 暫以 `relative` 相容，並標記 legacy。
- 新 API 直接移除 `world_x/world_z`，不保留相容層。
- 舊 scene 若缺少新版 frame metadata，拒絕載入，不自動修補。

## 唯一座標契約

### SceneFrame

每一個 scene、GLB/PLY、Sionna map、ISS-UNet map、route 與 CFAR response 都必須引用同一個 frame：

```json
{
  "frame_version": 1,
  "frame_id": "scene-<id>",
  "origin": {
    "lat": 0.0,
    "lon": 0.0,
    "alt_m": 0.0
  },
  "alt_mode": "amsl",
  "axis": "ENU",
  "units": "m",
  "extent": {
    "min_e": -256.0,
    "max_e": 256.0,
    "min_n": -256.0,
    "max_n": 256.0
  },
  "display_margin_m": 32.0,
  "grid": {
    "rows": 128,
    "cols": 128,
    "pixel_size_e_m": 4.0,
    "pixel_size_n_m": 4.0
  }
}
```

### GPS ↔ ENU

使用場景中心做局部近似，距離範圍只有 512m，足以維持目前系統精度：

```text
E = (lon - origin.lon) × meters_per_degree_lon(origin.lat)
N = (lat - origin.lat) × meters_per_degree_lat
U = altitude_to_local_u(alt, alt_mode, origin.alt_m)
```

反向轉換：

```text
lon = origin.lon + E / meters_per_degree_lon(origin.lat)
lat = origin.lat + N / meters_per_degree_lat
alt = local_u_to_altitude(U, alt_mode, origin.alt_m)
```

### ENU ↔ 各子系統

```text
ENU：      E=東、N=北、U=上
Three.js： x=E、y=U、z=-N
Sionna：   x=E、y=N、z=U
Grid：     col=floor((E - min_e) / pixel_size_e_m)
           row=floor((max_n - N) / pixel_size_n_m)
```

Grid 的 `row=0` 是北側，`col=0` 是西側。超出 grid extent 的 ENU 點不產生有效 row/col；route payload 仍可攜帶 ENU 與 `inside_extent=false`。

## 資料流

```text
GPS / GPS CSV
  → SceneFrame 驗證
  → GPS ↔ ENU
  → 前端 ENU ↔ Three.js 顯示
  → API 以 ENU 傳遞
  → 後端 ENU ↔ Sionna 或 ENU ↔ Grid
```

禁止新的 Three.js ↔ Sionna 直接轉換。所有跨模組本地座標必須先回到 ENU。

## 建模與地圖重建

1. scene generation 以任意 `lat/lon` 建立中心 bbox，水平尺寸固定 512m。
2. Blender / basemap / PLY / GLB 使用同一個 origin 與 extent。
3. mesh 超出 `[-256,256]` 時裁切；不足時保留空白 cell。
4. GLB 匯出為 Three.js 軸：`x=E, y=U, z=-N`，前端以 identity transform 載入。
5. PLY/XML 與 Sionna 保持 `x=E, y=N, z=U`，由明確 adapter 送入 Sionna。
6. building height map、radio map、ISS-UNet grid 永遠使用 SceneFrame 的固定 bounds；不可再從 PLY 實際 bounds 反推範圍。
7. 新版 scene metadata 必須保存 frame、asset frame、grid spec 與生成中心。

舊 NTPU/NYCU assets 先由 `backup/legacy-scenes-20260712` tag 保留，之後需要使用時重新生成新版相容 assets。

## API 契約

新的本地位置 payload 使用：

```json
{
  "frame_id": "scene-abc",
  "enu": {
    "east_m": 12.5,
    "north_m": 30.0,
    "up_m": 18.0
  },
  "grid": {
    "row": null,
    "col": null,
    "inside_extent": false
  }
}
```

- GPS WebSocket 保留 `lat/lon/alt/alt_mode`。
- route、CFAR 與 ISS response 以 ENU 為本地位置來源。
- 所有 scene/map/route/CFAR response 帶 `frame_id` 與必要 frame metadata。
- `world_x/world_z` 直接移除。
- frame 缺失、版本不符或 scene_id 不符時回傳明確錯誤，不使用 NTPU/NYCU fallback。

## 預計修改邊界

### Backend

- 新增 `backend/app/coordinate_frame.py`：SceneFrame、GPS/ENU、ENU/Grid、ENU/Sionna 與 bounds 驗證。
- 修改 `backend/app/blender_generate_scene.py`：固定 512m bbox、輸出新版 frame、匯出 GLB/PLY 軸向與裁切。
- 修改 `backend/app/iss_unet_dataset_service.py`：固定 frame grid，不使用實際 PLY bounds。
- 修改 `backend/app/iss_real.py` 與 `backend/app/iss_unet_service.py`：route、CFAR、ISS projection 改為 ENU + grid。
- 修改 `backend/app/sionna_service_lite.py` 與 `backend/app/main.py`：所有 Sionna 輸入先使用 ENU adapter，移除內嵌 Three.js 軸轉換。
- 修改 scene / ISS API response，移除 `world_x/world_z`。

### Frontend

- 修改 `frontend/src/utils/geo.ts`：明確拆出 GPS↔ENU、ENU↔Three.js 與高度模式。
- 修改 `frontend/src/App.tsx`：live GPS、GPS replay、裝置位置與 route 走同一 frame；replay 使用每筆 `alt`。
- 修改 `frontend/src/hooks/useGeneratedScene.ts` 與 scene types：保存並驗證 active SceneFrame。
- 修改 heatmap、route、CFAR overlay：使用 ENU 或 frame-derived Three.js 座標，不再讀 `world_x/world_z`。
- 修改 GPS CSV / device payload 型別，加入 `alt_mode` 與 frame status。
- NTPU/NYCU config 只作可選場景，不提供座標 fallback。

## 錯誤與顯示行為

- 地圖投影超出固定 extent：不產生有效 grid index，保留 ENU 並標記 `inside_extent=false`。
- GPS / replay 位於 extent 外但不超過 32m margin：`inside_extent=false`、`displayable=true`，仍顯示真實位置。
- GPS / replay 超過 32m margin：`out_of_frame=true`，保留原始資料但不顯示。
- 不允許把超界點夾到 `±256m`，避免製造假位置。
- 不允許使用 `VITE_SCENE_SCALE`、`ALT_GAIN` 或固定 marker 高度改變資料座標。

## 驗證策略

- origin 轉換為 ENU 必須是 `(0,0,0)`。
- 東、北、上方向分別驗證 Three.js 為 `(+x, 0, 0)`、`(0, 0, -z)`、`(+y)`。
- Sionna 方向驗證為 `(E,N,U)`。
- GPS ↔ ENU round-trip 誤差控制在測試允許的小數誤差內。
- Grid row/col 驗證北向 row 減少、東向 col 增加，以及四個邊界 cell。
- 固定 extent 驗證為 `512 × 512m`，pixel 為 `4m`。
- 顯示 margin 驗證 32m 內顯示、超出後隱藏且不夾值。
- GPS replay 的不同 alt 會產生不同 Three.js `y`。
- 舊 metadata 或缺少 frame 的 scene 會被拒絕。
- NTPU/NYCU 新版 scene 的 GLB、PLY、building map、radio map、ISS grid 使用同一 frame。
