# USRP Mission Service 設計

## 背景

目前前端的 USRP 任務流程預期 Raspberry Pi 端支援 mission-aware contract：

- `TEST` 啟動 `drone_test.service`
- `USRP` 啟動 `drone.service`
- 後端在 start 前寫入 mission env
- Raspberry Pi 寫入 mission state
- stop/finalize 後上傳 `noise.csv`

實際 SSH 檢查結果：

- `drone_test.service` 存在，執行 `/home/user/rx_sampling/rx_no_gui_test.py`
- `drone.service` 存在，執行 `/home/user/rx_sampling/rx_no_gui.py`
- `/run/simworld` 不存在
- `/var/lib/simworld/capture` 不存在
- `/home/user/pi_radio_stack.sh` 不存在
- 現有 service 沒有 `EnvironmentFile=/run/simworld/usrp.env`
- `rx_no_gui.py` 與 `rx_no_gui_test.py` 都以相對檔名 `noise.csv` 寫出資料；在 `WorkingDirectory=/home/user/rx_sampling` 下，實際輸出是 `/home/user/rx_sampling/noise.csv`

因此後端以為 Raspberry Pi 已支援 mission env/state/upload，但 Pi 端仍是舊式直接啟動腳本，造成 `/api/capture/usrp/start` 500 與任務狀態不完整。

## 目標

將 Raspberry Pi 端更新成 mission-aware service，但只保留目前需要的兩個 no-GUI RX 腳本：

- `TEST` 使用 `/home/user/rx_sampling/rx_no_gui_test.py`
- `USRP` 使用 `/home/user/rx_sampling/rx_no_gui.py`

清掉舊 stack 假設，不再使用：

- `chan_est_rx.py`
- `chan_est_tx.py`
- `noise.py`
- `zmq_to_noise_csv.py`

未來可擴充：

- `tx_no_gui.py`
- `jam_no_gui.py`

但 TX/Jammer 必須有明確 env 開關才啟動，不做自動偵測。

## RasPi Service Contract

Raspberry Pi 端使用單一 wrapper：

```text
/home/user/pi_radio_stack.sh
```

兩個 systemd service 都執行同一個 wrapper，但指定不同 RX entrypoint。

`drone_test.service`：

```ini
[Service]
User=user
WorkingDirectory=/home/user
Environment=MODE=test
Environment=RX_SCRIPT=/home/user/rx_sampling/rx_no_gui_test.py
Environment=TX_SCRIPT=/home/user/rx_sampling/tx_no_gui.py
Environment=JAMMER_SCRIPT=/home/user/rx_sampling/jam_no_gui.py
Environment=START_TX=0
Environment=START_JAMMER=0
EnvironmentFile=-/run/simworld/usrp.env
ExecStart=/bin/bash /home/user/pi_radio_stack.sh
KillMode=control-group
TimeoutStopSec=20s
Restart=no
```

`drone.service`：

```ini
[Service]
User=user
WorkingDirectory=/home/user
Environment=MODE=usrp
Environment=RX_SCRIPT=/home/user/rx_sampling/rx_no_gui.py
Environment=TX_SCRIPT=/home/user/rx_sampling/tx_no_gui.py
Environment=JAMMER_SCRIPT=/home/user/rx_sampling/jam_no_gui.py
Environment=START_TX=0
Environment=START_JAMMER=0
EnvironmentFile=-/run/simworld/usrp.env
ExecStart=/bin/bash /home/user/pi_radio_stack.sh
KillMode=control-group
TimeoutStopSec=20s
Restart=no
```

後端 start 前寫入：

```text
/run/simworld/usrp.env
```

最少包含：

```text
MISSION_ID=<mission_id>
MISSION_STATE_DIR=/var/lib/simworld/capture
UPLOAD_API_URL=http://<laptop-ip>:8888/api/usrp/upload-noise-csv
WORKDIR=/home/user/rx_sampling
NOISE_CSV=/home/user/rx_sampling/noise.csv
SCENE=NTPU
MAP_TYPE=iss
```

## Mission 狀態、snapshot 與 reconciliation

`GET /api/capture/status` 只回傳主機已持久化的 local snapshot，不在一般輪詢中等待 Raspberry Pi SSH；這讓前端在 Pi 離線至少一分鐘時仍能立即顯示最後可信資料。每個 GPS/USRP child 都保留 `last_attempt_at`、`last_success_at`、`refresh_state`、`consecutive_failures` 與 `next_retry_at`。

- `connection=offline` 只表示目前無法連到裝置，不表示 service 已停止。
- 最後可信的 running/stopping 在失聯時保留為 `presumed_running`；`reconciling` 表示正在重新確認。
- USRP 只有成功的 `systemctl is-active` 與 mission state read 才能確認 stopped/file state。
- GPS 只有本地 recorder/process 與檔案 finalization 證據才能確認完成。
- `upload_pending` 表示 Pi 上的 CSV 已完成但尚未成功傳回；不可顯示為 completed。
- reconciliation 只觀察狀態，不啟動、停止或偷偷上傳；已 `uploaded`/`completed` 的 mission 必須保持 idempotent。

自動 USRP reconciliation 使用 5、10、20、30 秒，之後固定 30 秒的 bounded backoff；成功後清零。手動 `Refresh GPS`、`Refresh USRP` 與 `Refresh all` 跳過 backoff，但仍受同 mission single-flight 保護，不建立重複 SSH probe。`Refresh all` 先取得 local snapshot，再依 mission id 分別呼叫 GPS 與 USRP refresh；GPS 與 USRP 的 busy/error 狀態彼此獨立。

Timeout budget：SSH connect/banner/auth 12 秒、單一 command 8 秒、完整 reconciliation 25 秒、Start/Stop 35 秒、upload retry 20 秒；API snapshot 5 秒、refresh 30 秒、Start/Stop 40 秒；前端 snapshot 5 秒、operation 45 秒。refresh warning 只記錄 device、mission id、attempt、last success、next retry 與 exception type，不記錄密碼、token、完整 URL 或 `.env`。


每個 mission 都有獨立 Pi 端資料夾：

```text
/var/lib/simworld/capture/<mission_id>/
```

內容：

```text
mission.json
noise.csv
```

wrapper 狀態流程：

1. start 時建立 mission dir。
2. 寫 `mission.json`：`state=starting`, `upload_state=recording`。
3. 啟動 `RX_SCRIPT`。
4. RX running 後寫 `state=running`。
5. stop/TERM/EXIT 時進入 `stopping_service`，bounded cleanup 最多 graceful 10 秒，再 force confirmation 2 秒。
6. 寫 `phase=finalizing_file`，先把工作目錄的 `NOISE_CSV` copy 到 mission dir 的 `noise.csv`。
7. 寫 `state=stopped`, `upload_state=upload_pending`，讓 service 先正常結束；上傳由獨立的 host-side upload retry 流程執行，前端不呼叫不存在的 retry route。
8. 上傳成功後寫 `upload_state=uploaded`；失敗時保留檔案與 `upload_pending`，前端顯示 CSV 已保存並提供 Refresh 以確認最新狀態。

檔案保護規則：

- 上傳成功前不刪除 mission dir 的 `noise.csv`。
- 新任務不能覆蓋舊任務 mission dir 的 `noise.csv`。
- 固定工作目錄 `noise.csv` 只視為 RX 腳本輸出，不作為唯一可靠來源。
- 如果 Raspberry Pi 斷電，已 copy 到 mission dir 的舊任務資料保留；正在寫入中的工作目錄 `noise.csv` 可能不完整，這會標為 failed 或 upload_pending。

## 後端行為

後端維持目前前端 API：

- `POST /api/capture/usrp/start`
- `POST /api/capture/usrp/stop`
- `GET /api/capture/status`
- `POST /api/capture/gps/refresh?mission_id=...`
- `POST /api/capture/usrp/refresh?mission_id=...`

修正點：

- start setup 建立 `/run/simworld` 與 `/var/lib/simworld/capture/<mission_id>`。
- `/run/simworld` 或 `/var/lib/simworld` 權限不足時使用既有 sudo fallback。
- `UsrpControlError` 與 remote setup/start 失敗轉成 `CaptureUnavailableError`。
- API 回 JSON 503，不再回純文字 500。
- launch 失敗寫回本機 `incoming/<mission_id>/capture.json` 的 `usrp.error`。
- status 讀取 Pi 端 `mission.json`，把 `recording/finalizing/upload_pending/uploaded/failed` 映射到前端 file state。
- status request 逾時只回安全的 504，並保留既有可信狀態；不把 Pi 離線誤寫成 stopped/failed。
- Start/Stop/refresh 使用 bounded deadline；Stop 不同步等待 upload，避免資料傳輸阻塞停止流程。

## 測試與驗收

Backend unit tests：

- `TEST` mode 對應 `drone_test.service`。
- `USRP` mode 對應 `drone.service`。
- start 會先寫 `/run/simworld/usrp.env`。
- remote setup 權限不足會 sudo fallback。
- `start_capture_job` 失敗時 API 回 JSON 503。
- launch 失敗會寫入本機 capture state 的 `usrp.error`。

RasPi wrapper contract tests：

- wrapper 要求 `MISSION_ID`。
- wrapper 支援 `RX_SCRIPT`。
- `START_TX=0` 時不啟動 TX。
- `START_JAMMER=0` 時不啟動 Jammer。
- finalization 會先 copy `NOISE_CSV` 到 mission dir。
- upload 失敗保留 mission dir 的 `noise.csv` 並寫 `upload_pending`。

Manual acceptance：

- 前端選 `TEST` 後 Start USRP，Pi 端啟動 `drone_test.service`。
- 前端選 `USRP` 後 Start USRP，Pi 端啟動 `drone.service`。
- Stop 後 Pi 端保留 `/var/lib/simworld/capture/<mission_id>/noise.csv`。
- `upload_pending` 時前端顯示 CSV 已保存，不顯示不存在的 `Retry upload` 按鈕；上傳重試由 host-side 既有流程處理。
- Pi 離線時前端顯示 `Offline`、last-seen 與 retry countdown；GPS 與 USRP 可分開 Refresh，任一裝置離線不會鎖住另一張卡。
- Stop 未確認時保留 `presumed_running/reconciling`，不可使用人工 force-state 取代真實 service/file 證據。
- 再次 start 不會覆蓋前一個 mission dir 的檔案。

## 明確不做

- 不啟用 `chan_est_rx.py`、`chan_est_tx.py`、`noise.py`、`zmq_to_noise_csv.py`。
- 不自動偵測並啟動 `tx_no_gui.py` 或 `jam_no_gui.py`。
- 不改前端按鈕與 API 路由命名。
- 不要求 service 開機自動啟動。
