# ISS_UNET Noise/GPS Context

這個 context 定義 ISS_UNET「Noise with GPS」流程中，雜訊測量與 GPS 路徑位置的共同語言。

## Language

**有效雜訊值**：
`noise_floor_db` 小於 -1 dB 的雜訊測量值；大於或等於 -1 dB 的讀值不被視為可用測量。
_Avoid_: 門檻以上雜訊值、補零、截斷值

**位置保留點**：
已與 GPS 時間對齊的路徑位置，即使沒有有效雜訊值仍保留；它不代表有效的雜訊測量。
_Avoid_: 有效雜訊點

**雜訊門檻過濾**：
將 `noise_floor_db` 大於或等於 -1 dB 的測量排除在計算之外；此規則可由每次 ISS_UNET 請求的選項控制，預設啟用。
_Avoid_: 補零、門檻值截斷

**綁定任務（Bound Mission）**：
AP3 與 USRP 共用同一個 `mission_id` 的量測任務；兩個裝置仍各自保有獨立的任務子狀態。
_Avoid_: Bind 模式、綁定裝置

**裝置健康（Device Health）**：
裝置目前是否可參與新任務的即時狀態，不會回寫或改變既有任務的結果。
_Avoid_: 任務狀態、裝置任務狀態

**任務子狀態（Mission Child State）**：
AP3 或 USRP 在特定任務中的 Connection、Service、File 與 Error 狀態；它描述該次任務的歷程與結果，而非裝置現在是否可用。
_Avoid_: 裝置健康、目前裝置狀態

**停止重試（Retry Stop）**：
綁定任務中針對尚未確認停止的單一任務子項再次送出停止要求；它不會重送另一個已停止子項，也不會強制把未知狀態標記為完成。
_Avoid_: 強制停止、手動完成

**AP3 採樣接續（AP3 Capture Resume）**：
AP3 在允許的恢復期限內重新連線後，沿用原 `mission_id` 並接續寫入同一份 `gps.csv`；它不是新任務，也不會補造中斷期間的 GPS。
_Avoid_: 重新開始任務、補回 GPS

**恢復逾期（Resume Timeout）**：
AP3 重連時已超過任務允許的接續期限；裝置健康可以恢復，但原任務的 AP3 採樣不可再接續。
_Avoid_: 任務逾時、裝置離線

**降級任務（Degraded Mission）**：
綁定任務仍未結束，但其中一個任務子項異常或停止結果尚未確認，另一個子項仍可繼續處理。
_Avoid_: 部分失敗、已失敗任務

**警告完成（Completed with Warning）**：
綁定任務已停止且沒有狀態不明的程序，其中一個任務子項完整成功，另一個子項失敗或不完整；失敗的子項必須明確標示為 GPS 或 Noise failed，且可保留部分成果。
_Avoid_: 降級任務、部分完成

**部分 GPS 成果（Partial GPS Result）**：
AP3 採樣中斷或恢復逾期前已成功寫入的有效 GPS 紀錄；資料會保留並可使用，但不代表該任務的 GPS 採樣完整完成。
_Avoid_: 失敗檔案、完整 GPS 成果
