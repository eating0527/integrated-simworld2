# 採樣控制與歷史任務介面

Status: ready-for-agent

採用 B 原型：即時採樣控制導軌與 Historical Mission List 分離。

## Problem Statement

操作者在筆電上的深色監控介面中，需要同時判讀即時採樣、硬體健康、任務收尾與匯入的歷史資料。現有採樣面板將裝置健康與任務子狀態混在高密度文字中；Historical Mission List 缺乏選取後的 artifact 判讀與明確的下一步。13 吋 MacBook 或瀏覽器縮放後，雙側欄更會壓縮 3D 主場景與控制內容。

## Solution

採用 B 版型，將左欄的即時採樣控制與右欄的 Historical Mission List 明確分工。採樣控制以 Control Mode 為入口，呈現 Bound Mission 或 Independent Capture 的可操作狀態；歷史區只呈現 Mission Bundle 的 mission_id、updated_at、GPS／Noise artifact 與 GPS 軌跡預覽。介面在 1200px 以下轉為抽屜式側欄，並在窄欄保留關鍵安全狀態而收合診斷細節。

## User Stories

1. 作為現場操作者，我想在採樣控制面板先看見 Control Mode，才能知道目前要控制的是 Bound Mission 或 Independent Capture。
2. 作為現場操作者，我想在 Independent Capture 中分別開始或停止 GPS 採樣與 Noise 採樣，才能維持兩個服務的獨立生命週期。
3. 作為現場操作者，我想在 Bound Mission 中只看到開始或停止綁定任務的共同控制，才能避免混合的啟動路徑。
4. 作為現場操作者，我想分別看見裝置就緒與任務狀態，才能不把硬體恢復誤讀為舊任務完成。
5. 作為現場操作者，我想在任何停用控制旁看見具體阻擋原因，才能知道如何解除條件。
6. 作為現場操作者，我想以準備、錄製、收尾或上傳等群組化進度判讀採樣，才能快速掌握目前階段。
7. 作為現場操作者，我想在錯誤所屬的 GPS 或 Noise 區塊看到錯誤與恢復操作，才能直接處理故障來源。
8. 作為現場操作者，我想在窄側欄仍看到 Connection、Phase、File、錯誤與模式切換阻擋，才能安全操作。
9. 作為現場操作者，我想查看 Historical Mission List 中最新更新的 Mission Bundle，才能快速找到新匯入資料。
10. 作為現場操作者，我想分別判讀 GPS 與 Noise 的 Healthy Artifact、Invalid Artifact 與缺少 artifact，才能決定資料可否套用。
11. 作為現場操作者，我想讓 Mission Selection 與 GPS 軌跡預覽中成為不同狀態，才能在只有 Noise artifact 時仍可選取並套用資料。
12. 作為現場操作者，我想在選取 Mission Bundle 後看到摘要與唯一的套用至模擬主操作，才能在不誤改 Simulation Mode 的前提下套用資料。
13. 作為現場操作者，我想讓 Historical Mission List 初始收合、匯入傳入任務成功後展開，才能兼顧主場景空間與匯入回饋。
14. 作為筆電使用者，我想在 1280px 寬度仍可使用雙側欄、在 1164px 寬度改用抽屜，才能保有足夠的 3D 場景與可讀控制。
15. 作為鍵盤與輔助技術使用者，我想使用正確焦點、停用理由與可辨識文字操作所有控制，才能安全完成採樣與資料套用。
16. 作為 Chrome 或 Brave 使用者，我想在頁面縮放後仍無水平捲軸或被截斷的必要操作，才能在不同筆電上可靠工作。
17. 作為操作者，我想讓青色、綠色、琥珀色與紅色保持固定語意，才能快速判讀操作、就緒、注意與危險狀態。
18. 作為操作者，我想獲得快速按壓與狀態變更回饋而非持續動畫，才能維持高頻控制的專注。

## Implementation Decisions

- 正式介面採用 B 原型的結構：左側呈現 live Control Mode 與採樣控制，右側呈現 Historical Mission List；原型僅作決策依據，不能直接升級為正式元件。
- Historical Mission List 只呈現 Mission Bundle。Bound Mission 與 Independent Capture 的 live 狀態不得出現在 Mission Bundle 的列表或詳細摘要。
- 採樣面板的頂部使用固定可見的 Control Mode 分段選擇器，名稱為「獨立採樣模式」與「綁定任務模式」。任一未收尾任務存在時，維持既有模式切換阻擋契約與訊息。
- Independent Capture 保留 GPS 採樣與 Noise 採樣各自的 Start／Stop 控制；Bound Mission 只保留開始綁定任務與停止綁定任務。停止綁定任務維持單擊危險操作，不加入長按或二次確認。
- 面板以「裝置就緒」表示 Device Health，以「任務狀態」表示 Mission Child State；兩者不可合併為模糊的單一狀態。
- 主畫面進度採群組化呈現：GPS 為準備、錄製、收尾；Noise 為連線與設定、錄製、收尾與上傳。完整 Phase 保留於詳細狀態。
- 關鍵錯誤顯示在對應的 GPS 或 Noise 區塊並附既有可用恢復操作；面板標頭只呈現整體摘要，僅共同錯誤可以顯示於標頭。
- 窄採樣容器將上次任務、最後 GPS 與完整步驟收合；Connection、Phase、File、錯誤與模式切換阻擋必須保持可見。
- 所有使用者操作、狀態標題與空狀態訊息使用繁體中文。開始與停止使用「動詞＋明確對象」格式；USRP 僅用於硬體或模式名稱，開始與停止的任務名稱為 Noise 採樣。
- Historical Mission List 維持後端的最新 updated_at 優先排序。第一版不提供搜尋、篩選或排序控制。
- Mission Bundle 選取後顯示 GPS／Noise artifact 摘要、是否 GPS 軌跡預覽中與套用至模擬主操作。Apply Mission 仍只套用 Healthy Artifact，缺少 artifact 保留既有 Simulation Panel CSV，且不改變 Simulation Mode。
- Historical Mission List 初始收合；成功匯入傳入任務後才展開，Refresh 與背景更新不自動展開。
- 1200px 以下使用抽屜式側欄；1200px 以上維持左右側欄。採樣容器在約 320px 以下使用緊湊呈現。左欄既有最大寬度 360px、右欄既有最大寬度 460px 不增加。
- 桌面字級維持固定層級而非隨 viewport 縮小：標題約 14px、目前狀態約 13px、一般狀態約 12px、標籤與時間約 11px。主要操作高度為 40px，次要操作至少 34px。
- 青色表示可操作主動作與選取；綠色表示確認就緒或完成；琥珀色表示等待、上傳或不確定；紅色表示失敗與停止。顏色以文字與圖示或狀態文字補強。
- 新增動效限於按鈕按壓、抽屜開闔與狀態變更；時長分別約 160ms、220ms、180ms。錄製中不使用持續脈衝，並遵守 reduced motion 設定。

## Testing Decisions

- 以現有採樣控制元件測試作為即時狀態與 Start／Stop 控制的主要 seam；測試外部可見文案、可用性、停用理由、Control Mode 阻擋與正確 API 動作，不測內部排版實作。
- 以現有 Historical Mission List 元件測試作為 Mission Bundle seam；測試最新清單、artifact 狀態、選取與預覽分離，以及只套用 Healthy Artifact 的既有契約。
- 以既有 Workspace 測試作為抽屜的行為 seam；測試鍵盤 focus、Escape 關閉與 aria-expanded／aria-controls 不退化。
- 新增最小的元件測試，驗證已採用的中文操作文案、錯誤歸屬、未收尾任務的模式切換阻擋，以及匯入成功後的 Historical Mission List 展開。
- 使用 Chrome 與 Brave 進行手動視覺驗收，覆蓋 1280×800、1164×727、1536×864、1920×1080 CSS viewport；確認沒有水平捲軸、必要資訊不截斷、兩欄或抽屜切換符合規格。
- 前端變更後執行受影響的 Vitest 測試與前端 build；視覺驗收採真實瀏覽器而非快照像素比對。

## Out of Scope

- Device Panel、UAV Control、Simulation Panel、Controller Screen、Photo Viewer 的視覺重設計。
- 後端 API、capture.json、WebSocket 事件、裝置健康邏輯、Mission Bundle schema 或 artifact 驗證規則的變更。
- Historical Mission List 的搜尋、篩選、手動排序或批次套用。
- 將 prototype 的靜態資料、DEV gate 或樣式直接保留在正式產品中。
- 新增停止綁定任務的二次確認、長按或 modal 流程。

## Further Notes

- 原型已解答版型選擇，正式實作前應將 prototype 留在 throwaway 分支或移除其 DEV gate，避免進入正式功能交付。
- 開始後建議將工作拆分為共用響應式樣式、採樣控制重構、Historical Mission List 重構與整合驗收等可獨立驗證的工作項。
