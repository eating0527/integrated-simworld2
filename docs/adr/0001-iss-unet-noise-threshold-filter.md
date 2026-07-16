# ISS_UNET Noise 門檻過濾

ISS_UNET 的 `Noise with GPS` 重建與統計流程使用每次請求的 Noise 門檻開關，預設啟用；啟用時只有 `noise_floor_db < -1 dB` 的值參與計算，`>= -1 dB` 與格式無效值不進入模型，但可保留有效時間所對應的 GPS 位置為空值位置。關閉時恢復既有數值處理，原始 `noise.csv` 不修改；過濾數量與時間未對齊數量分別回傳，空值位置以白色框線透明中心顯示。
