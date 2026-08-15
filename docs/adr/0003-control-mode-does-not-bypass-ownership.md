# Control mode does not bypass hardware ownership

Control Mode 是採樣面板的 Bound 或 Independent 操作視圖，不會改寫既有 mission 或硬體服務。操作者可以隨時切換視圖，以檢視各模式的任務狀態。

Independent Capture 中，AP3／無人機遙控器與 Raspberry Pi／Noise 控制平面可完全分開操作：一側任務的 Running、Presumed running、Stopping 或 Stop failed 不限制另一側的 Start 或 Stop。

但切換到 Bound 視圖不代表硬體已釋放。Start Bound Capture 仍只有在 AP3 與 Raspberry Pi 都健康、且沒有任何仍佔用對應硬體的任務時才可執行。這避免同一硬體在舊 Independent mission 尚未安全結束時被重複啟動。

切換任一 Control Mode 前，系統都會檢查 GPS 與 Noise 任務。若任一服務執行中、停止中或收尾中，UI 保留原模式並提示使用者先停止當前 mission；不顯示二次確認，也不在背景停止服務。Noise 的 Upload Pending 仍屬收尾中，必須成功 Uploaded 才能切換。Completed、Failed 與 Resume Timeout 都是終止結果，可直接切換；它們會留作歷史資料但不恢復 child 狀態。乾淨面板仍分別顯示 GPS 與 Noise 上一次 mission 的開始時間；同一 Bound Mission 的時間會出現在兩個區塊。

重新整理 frontend 後，未收尾的 GPS、Noise 或 Bound Mission 必須從持久化 mission state 顯示目前狀態與控制；backend restart 後接管既有 GPS recorder process 不屬於這項保證。

Bound Mission 與 Independent Capture 不可同時有未收尾任務。Bound Mission 任一 child 未收尾時，系統拒絕建立 Independent GPS 或 Noise mission；Independent GPS 或 Noise 任一未收尾時，系統拒絕 Start Bound Capture。Independent 模式內的 GPS 與 Noise 仍可彼此獨立執行與停止。
