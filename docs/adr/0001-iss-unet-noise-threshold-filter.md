# ISS_UNET Noise 門檻過濾

ISS_UNET 的 `Noise with GPS` 重建與統計流程使用每次請求的 Noise 門檻開關，預設啟用；啟用時只有 `noise_floor_db < -1 dB` 的值參與計算，`>= -1 dB` 與格式無效值不進入模型，但可保留有效時間所對應的 GPS 位置為空值位置。關閉時恢復既有數值處理，原始 `noise.csv` 不修改；`filtered_noise` 計算有有效時間但被排除的讀值，`skipped_noise` 計算無效時間或未被過濾但無法對齊 GPS 的讀值，`usable_noise` 計算成功對齊且可計算的讀值，三者不重複。空值位置以白色框線透明中心顯示。
