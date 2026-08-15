# ISS_UNET Noise/GPS Context

## Mission Import Language

**Mission Bundle**:
An imported mission record uniquely identified by `mission_id`, containing the available GPS, Noise, and capture metadata artifacts. A trajectory event is only its GPS visualization when GPS is available.
_Avoid_: Mission import, trajectory event

**Invalid Artifact**:
A present GPS or Noise file that fails header validation and therefore is not an importable artifact. It remains distinct from a missing artifact and never replaces a verified artifact of the same Mission Bundle.
_Avoid_: Missing file, absent data

**Healthy Artifact**:
A GPS or Noise artifact that is present and has passed header validation. Mission selection shows `[GPS]` and `[NOISE]` independently for healthy artifacts, or `[N/A]` when neither exists; measurement rows are filtered by Simulation or ISS-UNet.
_Avoid_: Complete mission, import status

**Artifact Header Contract**:
A healthy GPS artifact has exactly `time_stamp,lat,lon,alt,alt_mode` as its header. A healthy Noise artifact includes `time_stamp,noise_floor_db` and may contain extra columns.
_Avoid_: Row validation, sample validation

**Apply Mission**:
The explicit action that replaces each corresponding Simulation Panel CSV with a healthy artifact from the selected Mission Bundle. An artifact absent from that bundle leaves the panel's current CSV unchanged; manual upload and clearing remain available.
_Avoid_: Select trajectory, replace all files

**Simulation Mode**:
The user-selected ISS-UNet input mode. Applying a Mission Bundle updates CSV artifacts only and never changes this mode.
_Avoid_: Mission mode, import mode

**Applied Artifact Snapshot**:
The CSV content currently held by the Simulation Panel after manual upload or Apply Mission. Later Mission Bundle imports do not alter this snapshot; applying the Mission again is required.
_Avoid_: Live mission link, automatic refresh

**Metadata-only Mission Bundle**:
A Mission Bundle with capture metadata but no healthy GPS or Noise artifact. It remains visible in the import panel with `[N/A]`; a folder with no recognized artifacts is not a Mission Bundle.
_Avoid_: Empty mission, hidden mission

**Historical Mission List**:
The single panel that lists imported Mission Bundles and their healthy artifact labels. It supersedes the historical trajectory list without creating a separate mission-import panel.
_Avoid_: Mission import panel, duplicate panel

**Mission Selection**:
Selecting a Mission Bundle displays its GPS trajectory when available. It does not modify Simulation Panel input; Apply Mission is the separate, explicit action that does so.
_Avoid_: Automatic apply, live selection

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

**控制模式（Control Mode）**：
採樣面板的 Bound 或 Independent 操作視圖；切換只決定控制與狀態投影，不會改寫既有任務或硬體服務。
_Avoid_: 綁定任務、任務模式

**獨立採樣（Independent Capture）**：
GPS 與 Noise 各自建立並控制不同 `mission_id` 的採樣。AP3／無人機遙控器與 Raspberry Pi／USRP B210 是獨立硬體，因此任一側的任務狀態不會限制另一側的 Start 或 Stop；各側仍遵守自身的裝置健康與同服務 ownership 檢查。
_Avoid_: 單人採樣、未綁定任務

**乾淨控制面板（Clean Control Panel）**：
Bound 或 Independent Control Mode 的閒置操作視圖；它不恢復舊 mission 的 child 狀態、不建立新 mission，也不啟動硬體。沒有未收尾任務時，Independent 的乾淨面板是預設面板。兩種模式的面板都跨 Control Mode 保留各服務上一次 mission 的開始時間與 mission id 最後五碼；同一 Bound Mission 的 GPS 與 Noise 區塊各自顯示相同時間與尾碼。使用者按 Start UAV 或 Start USRP 時才為該服務建立新的 Independent Capture。
_Avoid_: 重設任務、建立空任務

**操作時間格式（Operational Timestamp Format）**：
控制面板的上一次 mission 開始時間與既有 Raspberry Pi health 時間欄位都以 `Asia/Taipei` 的 `MM/DD HH:mm:ss` 顯示；沒有上一次 mission 時顯示 `—`。格式化不改變後端紀錄或 probe 判定語意。
_Avoid_: 完整 ISO 時間、無時區的原始字串

**模式切換停止確認（Mode Switch Stop Confirmation）**：
切換 Control Mode 前的安全檢查。系統先檢查 GPS 與 Noise 任務；任一服務執行中、停止中或收尾中（包括 Noise Upload Pending）時，維持原模式並提示使用者先停止當前 mission。Completed、Failed 與 Resume Timeout 都視為不再占用服務，可切換到另一個模式的乾淨控制面板。
_Avoid_: 強制切換、背景停止、切換停止確認

**前端 reload 恢復（Frontend Reload Recovery）**：
重新整理前端後，未收尾的 GPS、Noise 或 Bound Mission 必須重新顯示其目前狀態與可用控制。此恢復依賴持久化 mission state；backend restart 後接管既有 GPS recorder process 不在此保證範圍。
_Avoid_: backend process 接管、自動恢復歷史完成任務

**控制模式互斥（Control Mode Exclusivity）**：
未收尾的 Bound Mission 與未收尾的 Independent Capture 不可同時存在。Bound Mission 任一 child 未收尾時不可建立 Independent Capture；Independent GPS 或 Noise 任一未收尾時不可建立 Bound Mission。此限制不影響 Independent 模式內 GPS 與 Noise 的彼此獨立控制。
_Avoid_: 混合模式執行、跨模式接續

**Noise 模式獨立性（Noise Mode Independence）**：
Independent Control Mode 下，Test mode 與 USRP mode 僅受 Noise 自己的 mission 狀態與 Raspberry Pi health 限制；GPS 採樣不會鎖住 Noise mode 控制。
_Avoid_: GPS 模式、跨服務 mode lock

**模式切換阻擋提示（Mode Switch Blocker Notice）**：
模式切換因未收尾任務而被拒絕時的可操作說明。GPS、Noise 或兩者執行中時分別提示「請先停止 GPS 任務。」「請先停止 Noise 任務。」「請先停止 GPS 與 Noise 任務。」；Bound Mission 提示「請先停止當前任務。」；Noise 上傳中提示「請先等待 Noise 上傳。」。
_Avoid_: 一般錯誤、服務不可用

**Test Noise 採樣（Test Noise Capture）**：
由 Raspberry Pi 上的測試腳本產生的 Noise 採樣，不使用 USRP B210；它仍由 Raspberry Pi 的 Noise 控制平面管理。
_Avoid_: USRP 測試、模擬 GPS

**Noise 採樣（Noise Capture）**：
由 Raspberry Pi 的 Noise 控制平面執行的採樣任務，可使用 Test mode 或 USRP mode。使用者介面的開始與停止操作以「Noise 採樣」為對象；USRP 僅指硬體或模式名稱，不與採樣任務混用。
_Avoid_: 開始 USRP、停止 USRP

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
