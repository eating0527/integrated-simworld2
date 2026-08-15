# GPS data freshness is not a mission failure signal

AP3／無人機遙控器未連接 UAV 時，GPS recorder 可正常執行但不會產生 GPS 資料。系統不再因為超過固定時間沒有新的 GPS row，就將 GPS child 轉為 Reconciling、Presumed running 或觸發 AP3 Capture Resume。

AP3 明確離線與本機 recorder process 結束仍是獨立的安全訊號，維持既有的錯誤、停止與接續處理。此決策只移除「沒有 GPS data」作為採樣服務異常的推論，避免無 GPS 輸入時阻礙正常測試。

GPS recorder 正常停止時，只有 canonical header、沒有資料列的 `gps.csv` 仍視為完成；系統不將它轉為警告或失敗。
