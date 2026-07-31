# TX/Jammer 模型與地面圓框標記設計

## 目標

縮小 3D 場景中的 TX tower 與 Jammer 模型至目前顯示尺寸的 25%，並在各裝置底部增加與 ISS_UNET CFAR 干擾源相同視覺語言的圓形框線：TX 使用藍色、Jammer 使用綠色。

## 已確認的需求

- 現有 TX 模型縮放值為 `0.1`，改為 `0.025`。
- 現有 Jammer 模型縮放值為 `0.01`，改為 `0.0025`。
- TX 地面標記為藍色；Jammer 地面標記為綠色。
- 圓框貼在裝置的地面位置，隨裝置座標移動。
- 標記與對應角色的 `modelVisible` 開關同步顯示。
- CFAR 現有紅色高柱、底部圓框與標籤行為維持不變。
- 不修改 API、WebSocket 事件、裝置資料格式或座標轉換。

## 方案

新增獨立的 `DeviceGroundMarker` 元件，而不是把 TX/Jammer 標記邏輯塞進 `MainScene` 或改造 `CFARBeaconMarker`。元件只負責一個裝置的底部圓框，接收位置與角色顏色，並沿用 CFAR 的底部 ring/circle 幾何形式。這讓 CFAR 的干擾源語意維持獨立，也讓標記視覺設定可以用單元測試驗證。

## 元件與資料流

`MainScene` 仍從 `useDeviceStore` 取得裝置與 `modelVisible`，並依角色分組：

1. 若 `modelVisible.jammer` 為 true，對每個 Jammer 渲染縮小後的 `Jam` 與綠色 `DeviceGroundMarker`。
2. 若 `modelVisible.tx` 為 true，對每個 TX 渲染縮小後的 `Tower` 與藍色 `DeviceGroundMarker`。
3. `DeviceGroundMarker` 以裝置的 `[x, y, z]` 為 group 位置，ring/circle 在 group 內以小幅 `y` 偏移置於底部，避免與場景地面發生 z-fighting。

預計檔案責任如下：

- `frontend/src/components/scene/DeviceGroundMarker.tsx`：角色顏色、圓框幾何與渲染元件。
- `frontend/src/components/scene/MainScene.tsx`：渲染裝置模型與標記，並套用新的模型縮放值。
- `frontend/tests/device-ground-marker.test.mjs`：驗證角色顏色、固定視覺尺寸與底部標記設定。
- `frontend/src/components/scene/MainScene.test.tsx`：保留既有角色可見性回歸測試，並補充 TX/Jammer 標記數量與模型縮放 props 的測試。

## 視覺規格

- 使用水平 `ringGeometry` 作為主要圓形框線，旋轉至 XZ 地面平面。
- 可保留低透明度 `circleGeometry` 填色，使標記在深色場景中可辨識；主要識別仍是圓形框線。
- TX 顏色使用既有技術監控風格的藍色（`#2ea8ff`）；Jammer 顏色使用綠色（`#39e66d`）。兩者均使用半透明材質、關閉 depth write，避免遮擋 3D 場景。
- 圓框尺寸固定，不依裝置數量或模型縮放變化，確保多個裝置的定位標記一致且容易辨識。
- 不新增 HTML 標籤、浮動面板或會改變主要版面尺寸的 UI。

## 測試與驗收

先以測試描述新元件應提供的視覺設定，再實作最小行為：

- 標記設定對 TX 回傳藍色、對 Jammer 回傳綠色。
- 不同裝置或模型尺寸不會改變圓框的固定直徑與半徑。
- `MainScene` 在 TX/Jammer 可見時各渲染一個對應標記；隱藏某角色時，該角色的模型與標記同時消失，其他角色與 RX 不受影響。
- 前端執行 `npm test -- --run ...` 的受影響測試，接著執行完整 `npm test` 與 `npm run build`。

完成條件是：TX/Jammer 模型視覺尺寸為原本的四分之一；每個可見 TX 下方有藍色圓框、每個可見 Jammer 下方有綠色圓框；切換角色模型可見性後標記同步切換；既有 CFAR 標記測試與前端建置維持通過。
