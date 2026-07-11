# USRP 任務控制與離線恢復設計

日期：2026-06-24  
分支：`feat/usrp-job`

## 目標

讓前端能控制兩條可獨立運作的採樣流程：

- UAV：本機透過 USB 連接 AP3，產生 `gps.csv`
- USRP：後端透過 SSH 控制 Raspberry Pi 上的 systemd service，產生並回傳 `noise.csv`

兩條流程預設獨立操作。使用者開啟 Bind 後，才以同一個
`mission_id` 同步啟動並配對檔案。

系統必須支援：

- Raspberry Pi 與本機斷線後，遠端 service 繼續採樣
- 重連後恢復控制與真實狀態
- 單一路徑失敗不終止另一條路徑
- 停止 USRP 後，只有 CSV 安全落盤、上傳並由本機確認後才算完成
- 上傳失敗時保留檔案並自動重試
- 同一裝置同時間最多執行一個採樣任務

## 非目標

- 不新增 Raspberry Pi HTTP 控制服務
- 不導入 Redis、MQTT、RabbitMQ 或其他訊息佇列
- 不支援 Raspberry Pi 重開機後自動恢復採樣
- 不改變 Test 與 USRP service 內部的 GNU Radio 演算法
- 不要求 GPS 與 Noise 在單路測試時互相依賴

## 架構

採用「本機協調、遠端自治」。

### 本機後端

本機後端負責：

- 接收前端控制命令
- 保存任務及兩個子任務狀態
- 啟停本機 AP3 GPS worker
- 使用短生命週期 SSH 命令控制 Raspberry Pi systemd
- 接收並驗證 Raspberry Pi 上傳的 `noise.csv`
- 以 `mission_id` 將 `gps.csv` 與 `noise.csv` 放入同一任務目錄

SSH session 不是任務生命週期的擁有者。SSH 中斷只代表目前無法觀測
或控制 Raspberry Pi，不代表遠端 service 已停止。

### Raspberry Pi

Raspberry Pi 使用既有 systemd 管理兩種模式：

- Test：`drone_test.service`
- USRP：`drone.service`

兩個 unit 共用相同的任務執行契約：

- 從環境檔或啟動參數取得 `mission_id`
- 將當前任務狀態寫入持久化 `mission.json`
- 採樣資料寫入該任務專用目錄
- 收到 SIGTERM 時停止接收資料、flush 並關閉 CSV
- 停止後啟動或喚醒 uploader
- 上傳失敗時保留 CSV 並持續重試

## Bind 模式

Bind 預設為關閉。

### Bind OFF

UAV 與 USRP 完全獨立：

- 各自具有 Start、Stop、狀態與 mission
- 啟動前只檢查自身依賴
- UAV 可在 Raspberry Pi 離線時錄製 GPS
- USRP 可在 AP3 離線時錄製 Noise
- Test／USRP 模式只影響 Raspberry Pi service

### Bind ON

UAV 與 USRP 組成聯合任務：

- 開始前必須確認 AP3／USB GPS 與 Raspberry Pi 都可用
- 兩個子任務使用相同 `mission_id`
- 由共同 Start 同步啟動
- 仍分開監控、停止及保存檔案
- 提供個別 Stop 以及 Stop All
- 任一路徑失敗時，另一條繼續運作
- 聯合任務狀態顯示 `partial_failed`

Bind 不可在任一子任務執行期間切換。

## 任務模型

每個任務包含：

```text
mission_id
bind
selected_usrp_mode
created_at
started_at
finished_at
overall_state
uav
usrp
```

每個子任務分開保存三類狀態：

### Connection

- `ready`
- `offline`
- `unknown`

### Service

- `idle`
- `starting`
- `running`
- `presumed_running`
- `stopping`
- `stopped`
- `failed`

### File

- `none`
- `recording`
- `finalizing`
- `ready`
- `upload_pending`
- `uploaded`
- `failed`

任務總狀態：

- `ready`
- `starting`
- `running`
- `partial_failed`
- `finalizing`
- `completed`
- `failed`

## 啟動流程

### 獨立 UAV

1. 檢查 AP3／USB GPS 可用。
2. 建立 UAV mission。
3. 啟動 GPS worker 並寫入該 mission 的 `gps.csv`。
4. 回報 UAV connection、service 與 file 狀態。

### 獨立 USRP

1. 使用短 SSH 連線確認 Raspberry Pi 可達。
2. 確認 Test／USRP 目標 service 未執行其他任務。
3. 建立 USRP mission。
4. 將 `mission_id` 與上傳設定寫入 Raspberry Pi 任務環境。
5. 啟動選定的 systemd service。
6. 讀取 systemd 與 `mission.json` 確認已進入 running。

### Bind

1. 同時檢查 AP3／USB GPS 與 Raspberry Pi。
2. 任一依賴未 ready 時拒絕開始，不建立半啟動任務。
3. 建立共用 `mission_id`。
4. 持久化本機任務後，啟動 UAV 與 USRP 子任務。
5. 若啟動命令執行期間其中一路失敗，已啟動的一路不回滾，任務標記
   `partial_failed`。

## 離線與重連

### SSH 中斷

若最後已知 USRP service 正在執行：

- Connection 改為 `offline`
- Service 改為 `presumed_running`
- 不送出 stop 或 restart
- 不建立新任務

### 重連

後端重新取得：

- `systemctl is-active`
- service 最近日誌
- Raspberry Pi `mission.json`
- Noise CSV 路徑、大小及上傳狀態

以上資料用來校正本機狀態。若遠端 mission 與本機記錄相同，恢復控制；
若不同，顯示衝突並禁止直接啟動新任務，直到現有遠端任務被處理。

### Raspberry Pi 重開機

執行中的任務標記為 `failed`，不自動恢復採樣。若已有完整或部分 CSV：

- 保留檔案
- 標記失敗原因為 reboot 或 interrupted
- uploader 仍可嘗試補傳

## 停止與回傳交易

Stop 必須是可重複呼叫的冪等操作。

### USRP Stop

1. 後端送出 systemd stop。
2. systemd 傳送 SIGTERM。
3. 採樣程式停止接收新資料。
4. Logger flush 並關閉 `noise.csv`。
5. Raspberry Pi 更新 `mission.json`，包含：
   - 結束時間
   - 結果狀態
   - 失敗原因
   - CSV 路徑
   - CSV 大小
   - 檔案識別值
   - 上傳狀態
6. uploader 上傳 Noise CSV。
7. 本機確認 mission、檔名、大小及識別值。
8. 本機回傳接收成功。
9. Raspberry Pi 將上傳狀態設為 `uploaded`。
10. 前端才顯示 USRP 子任務 `completed`。

若上傳失敗：

- File 狀態為 `upload_pending`
- Raspberry Pi 保留 CSV
- uploader 定時重試
- 前端不得顯示 completed

若 stop 命令的 SSH 回應中斷，重連後先查詢 systemd 與 `mission.json`；
再次 Stop 不得破壞檔案或建立重複上傳。

### UAV Stop

1. 停止本機 GPS worker。
2. flush 並關閉 `gps.csv`。
3. 驗證檔案存在且可讀。
4. File 狀態改為 `ready`，代表檔案已由本機持有。
5. UAV 子任務才顯示 completed。

### Stop All

UAV 與 USRP 平行停止，各自完成自己的檔案交易。

- 兩路皆完成：任務 `completed`
- 一路完成、一路失敗或待上傳：任務 `partial_failed`
- 兩路皆失敗：任務 `failed`

## API 方向

保留簡單、明確的任務操作：

```text
GET  /api/capture/status
POST /api/capture/uav/start
POST /api/capture/uav/stop
POST /api/capture/usrp/start
POST /api/capture/usrp/stop
POST /api/capture/bind/start
POST /api/capture/bind/stop
```

`bind/stop` 代表 Stop All。個別 Stop 在 Bind ON 時仍可使用。

既有 `/api/usrp/sampling/*` 可在遷移期間保留相容層，但新前端只使用新的
capture API。相容層不得維護第二套任務邏輯。

Noise 上傳使用單一接收實作。既有 upload endpoint 可暫時保留路由別名，
但全部委派給同一個儲存與驗證函式。

## 前端

採樣控制面板分成兩區。

### UAV Status

- AP3／USB connection
- GPS service state
- GPS file state
- mission id
- Start UAV
- Stop UAV

### USRP Status

- Raspberry Pi connection
- Test／USRP 模式
- systemd service state
- Noise file／upload state
- mission id
- Start USRP
- Stop USRP

### Bind 控制

- Bind 開關預設 OFF
- 任一子任務執行時禁止切換
- Bind ON 時顯示共同 Start 與 Stop All
- 仍保留個別 Stop
- USRP 執行期間禁止切換 Test／USRP 模式

前端必須分別顯示 connection、service、file，不能用單一「已連線」或
「執行中」隱藏離線但仍採樣、已停止但待上傳等狀況。

## 錯誤處理

- 開始前檢查失敗：不建立執行中任務
- 啟動中單路失敗：保留成功路徑，總狀態 `partial_failed`
- AP3 中斷：UAV failed，USRP 繼續
- Raspberry Pi／SSH 中斷：USRP `presumed_running`，UAV 繼續
- systemd service 意外退出：USRP failed，若有 CSV 則繼續 finalization
- Noise 上傳失敗：`upload_pending` 並重試
- GPS 檔案 finalization 失敗：UAV file failed
- 遠端 mission 衝突：禁止新任務並要求先處理現有任務
- 回應不得包含 SSH 密碼或其他敏感設定

## 持久化

第一版不導入資料庫。

- 本機任務狀態使用 JSON 檔案保存於 `incoming/<mission_id>/`
- Raspberry Pi 使用任務專用目錄與 `mission.json`
- JSON 更新採用寫入暫存檔後原子取代，避免斷電留下半份狀態
- 重啟後掃描現有任務目錄恢復最後狀態

若未來出現多 Raspberry Pi、多使用者並行控制或需要查詢大量歷史任務，
再考慮資料庫與工作佇列。

## 驗證

最小必要測試：

1. Bind OFF 時 UAV 與 USRP 可在另一方離線時獨立啟動。
2. Bind ON 時兩方必須 ready，並取得相同 `mission_id`。
3. 同一裝置不可同時啟動第二個任務。
4. SSH 中斷後顯示 offline + presumed_running。
5. 重連後依 systemd 與 `mission.json` 恢復狀態。
6. 單一路徑失敗時另一條繼續，總狀態為 partial_failed。
7. USRP Stop 在 CSV 上傳完成前不得回報 completed。
8. 上傳失敗顯示 upload_pending 並保留檔案。
9. 重複 Stop 不重複破壞檔案或上傳。
10. Raspberry Pi 重開機後任務 failed，既有 CSV 仍可補傳。
11. 前端禁止在執行中切換 Bind 或 USRP 模式。
12. 前端分開呈現 UAV 與 USRP 的 connection、service、file 狀態。

## 遷移與清理

實作順序以不中斷現有流程為原則：

1. 建立共享任務模型與 capture API。
2. 讓既有 GPS worker 與 USRP 控制委派給新模型。
3. 更新 Raspberry Pi service 契約與 uploader。
4. 更新前端控制面板。
5. 保留舊 API 相容層完成驗證。
6. 移除重複 connect、disconnect、messages 與直接 WebSocket USRP 路徑。
7. 合併重複 CSV 上傳入口與工具。

清理工作必須在新流程通過整合測試後進行。
