# 裝置座標輸入模式設計

## 目標

在裝置設定面板中加入 GPS 經緯度與 xyz 座標切換，預設使用 GPS；TX、RX、Jammer 都能用 GPS 變更位置，並限制位置落在目前 scene 範圍內。

## 已確認需求

- 整個面板共用一個座標模式按鈕。
- 模式預設為 GPS 經緯度。
- GPS 與 xyz 都採「編輯草稿，按套用位置才生效」。
- 切換模式時放棄未套用草稿，從已套用位置重新計算另一模式。
- 高度沿用目前 `SceneFrame.alt_mode`。
- GPS、xyz 套用都必須落在目前 `SceneFrame.extent` 內。
- 使用簡單原生 SVG icon，不新增 icon 套件。
- 保持深色、半透明、技術監控風格與現有 CSS 變數。

## 資料模型與資料流

`Device.x/y/z` 是唯一 canonical 位置，不新增 `lat/lon/alt` 欄位。既有 payload、預設值與 backend contract 維持不變。

GPS 顯示流程：

```text
Device.x/y/z
  -> threeToEnu([x, y, z])
  -> enuToGps(enu, activeFrame, activeFrame.alt_mode)
  -> lat/lon/alt 欄位
```

GPS 套用流程：

```text
lat/lon/alt 草稿
  -> gpsToEnu(gps, activeFrame, activeFrame.alt_mode)
  -> enuToThree(enu)
  -> enuToGrid(enu, activeFrame).inside_extent
  -> updateDevice(id, { x, y, z })
```

xyz 套用流程先把 `x/y/z` 轉成 ENU，再用同一個 `inside_extent` 驗證，通過後才呼叫 `updateDevice`。驗證失敗時保留草稿、不更新 store，並顯示位置超出目前 scene 範圍。

scene extent 沿用現有半開區間規則：

- `east >= min_e` 且 `east < max_e`
- `north >= min_n` 且 `north < max_n`

高度不另外限制數值範圍；其意義由目前 `alt_mode` 決定。

## 元件與版面

`DevicePanel` 接收目前 `activeFrame`，並在面板層維護 `coordMode: 'gps' | 'xyz'`，預設為 `gps`。目前 `MinPanel` 的收合與抽屜行為保留。

移除 `MinPanel` 內容中重複的 `dp-header`，改成單一座標工具列：

```text
裝置設定                                      收合
位置座標                                      [GPS/XYZ icon]

TX                                             [+ 新增]
  名稱 [................................]
  位置
  緯度 [..............................]
  經度 [..............................]
  高度 [..............................] m
  功率 [..............................] dBm
  [套用位置]
  [儲存預設] [套用預設] [歸零]

RX
  同樣結構

Jammer
  同樣結構
```

xyz 模式只替換位置欄位為 `X / Y / Z`。所有角色都顯示「套用位置」；RX 套用後另外呼叫既有 `onApplyRxPosition`，同步 UAV 狀態。

座標欄位採單欄排列，輸入框使用 `width: 100%`、`min-width: 0`、`max-width: 100%`，符合桌面側欄與 1099px 以下抽屜的限制，不產生水平捲軸。

## 模式按鈕與無障礙

- GPS 模式顯示經緯線地球 SVG；xyz 模式顯示三軸箭頭 SVG。
- icon 只使用 `currentColor`，不新增外部依賴。
- 實際按鈕觸控區至少 44px，視覺圖示約 20px。
- 使用 `aria-pressed` 表示目前模式。
- `aria-label` 說明按下後的目的，例如「切換為 XYZ 座標」或「切換為 GPS 經緯度」。
- 使用 `title` 提供滑鼠提示，並保留 `:focus-visible` 樣式。
- 座標輸入區提供穩定的 `aria-controls` id。
- Escape 沿用 Workspace 現有抽屜關閉行為；不新增自訂 tooltip 或 modal。

## 草稿同步規則

- 每個裝置列的座標欄位只維護本地文字草稿。
- 輸入不會立即改變 store 或 3D 場景。
- 套用成功後，canonical xyz 更新，該列草稿重新由 canonical 位置產生。
- 切換 `coordMode` 時，所有列放棄草稿，從目前已套用 xyz 重新產生欄位。
- `activeFrame` 改變時，xyz 位置保持不變，GPS 欄位依新 frame 重新計算。
- 套用預設與歸零更新 canonical 位置後，草稿重新同步。
- 外部 RX/UAV 更新 canonical 位置後，該列草稿重新同步。
- 輸入欄位若有空字串、部分數字或非有限數值，套用按鈕不可執行。

## 顏色

只重用現有變數：

- 面板：`--panel-bg`、`--panel-border`
- 主要文字：`--text`、`--text-primary`
- 標籤與單位：`--text-muted`
- 輸入框：`--input-bg`
- 模式按鈕與 focus：`--accent-cyan`
- 套用位置：現有青綠色樣式
- 歸零與刪除：`--danger`

不新增第二套顏色系統；未套用草稿只以既有 accent 邊框提示。

## 修改範圍

- 修改 `frontend/src/components/ui/DevicePanel.tsx`：模式、GPS/xyz 顯示、草稿、套用與 extent 驗證。
- 修改 `frontend/src/App.tsx`：將 `activeFrame` 傳入 `DevicePanel`。
- 修改 `frontend/src/styles/main.scss`：面板工具列、單欄座標欄位、按鈕與 focus 樣式。
- 新增 `frontend/src/components/ui/DevicePanel.test.tsx`：面板互動與驗證測試。

不修改 `frontend/src/types/device.ts`、`frontend/src/store/useDeviceStore.ts` 的資料格式、`frontend/src/utils/geo.ts` 或 backend。

## 測試驗收

1. GPS 套用可正確更新 TX、RX、Jammer 的 xyz。
2. GPS 與 xyz 互相切換時都從已套用位置重新計算，不產生漂移。
3. 切換模式會捨棄未套用草稿。
4. GPS 緯度、經度越界與三欄不完整時不更新 store。
5. xyz 位置超出 scene extent 時不更新 store；邊界內位置可成功套用。
6. RX 套用仍同步 UAV position。
7. 模式按鈕具備正確的 `aria-pressed`、`aria-label`、`aria-controls`，可用鍵盤操作。
8. `npm test` 與 `npm run build` 通過。
