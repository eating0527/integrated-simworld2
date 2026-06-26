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
TimeoutStopSec=0
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
TimeoutStopSec=0
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

## Mission State 與檔案保護

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
5. stop/TERM/EXIT 時進入 finalization。
6. 先把工作目錄的 `NOISE_CSV` copy 到 mission dir 的 `noise.csv`。
7. 從 mission dir 上傳 `noise.csv`。
8. 成功後寫 `upload_state=uploaded`。
9. 失敗時保留檔案並寫 `upload_state=upload_pending`。

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

修正點：

- start setup 建立 `/run/simworld` 與 `/var/lib/simworld/capture/<mission_id>`。
- `/run/simworld` 或 `/var/lib/simworld` 權限不足時使用既有 sudo fallback。
- `UsrpControlError` 與 remote setup/start 失敗轉成 `CaptureUnavailableError`。
- API 回 JSON 503，不再回純文字 500。
- launch 失敗寫回本機 `incoming/<mission_id>/capture.json` 的 `usrp.error`。
- status 讀取 Pi 端 `mission.json`，把 `recording/finalizing/upload_pending/uploaded/failed` 映射到前端 file state。

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
- 上傳失敗時前端顯示 pending/error，不洗掉檔案。
- 再次 start 不會覆蓋前一個 mission dir 的檔案。

## 明確不做

- 不啟用 `chan_est_rx.py`、`chan_est_tx.py`、`noise.py`、`zmq_to_noise_csv.py`。
- 不自動偵測並啟動 `tx_no_gui.py` 或 `jam_no_gui.py`。
- 不改前端按鈕與 API 路由命名。
- 不要求 service 開機自動啟動。
