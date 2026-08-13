# 後端與硬體操作

這份文件涵蓋詳細操作細節：後端、AP3 bridge、Raspberry Pi USRP、Cloudflare tunnel。

## Windows 啟動腳本

常用指令：

```powershell
.\start.ps1
.\start.ps1 -NoTunnel
.\start.ps1 -NoAP3
.\start.ps1 -GpsCsv
.\start.ps1 -Reload
```

`start.ps1` 會啟動：

- backend: `http://localhost:8888`
- frontend: `http://localhost:5173`
- Cloudflare tunnel: `https://frontend.simworld.website`、`https://backend.simworld.website`
- AP3 bridge: USB ADB forward 到 `tcp:127.0.0.1:15760`

log 位置：

```text
.logs/backend.log
.logs/backend.log.err
.logs/frontend.log
.logs/frontend.log.err
.logs/tunnel.log
.logs/tunnel.log.err
.logs/ap3_bridge.log
.logs/ap3_bridge.log.err
.logs/ap3_gps_csv.log
```

本機只驗證前後端時，使用：

```powershell
.\start.ps1 -NoTunnel -NoAP3
```

這會避免啟動 Cloudflare tunnel 與硬體 AP3 bridge，適合 UI、API 與一般回歸測試。

服務停止後，才清理 runtime 產物：

```powershell
Remove-Item .logs -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item frontend\dist -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item .playwright-cli,.tmp,tmp,outputs,work -Recurse -Force -ErrorAction SilentlyContinue
```

不要用上述清理指令刪除 `backend/.venv`、`frontend/node_modules`、`.env`、模型權重或 `incoming` 中仍要保留的 mission。

## AP3 / M4P TOP USB

1. 遙控器用 USB 接到電腦。
2. 遙控器上允許 USB debugging / ADB 授權。
3. 確認 ADB 看得到裝置：

```powershell
.\tools\platform-tools\adb.exe devices
```

應看到類似：

```text
xxxxxxxx	device
```

4. 啟動：

```powershell
.\start.ps1
```

5. 確認後端收到資料：

```powershell
Invoke-RestMethod http://127.0.0.1:8888/api/gps/devices | ConvertTo-Json -Depth 5
```

## 手動重啟 AP3 bridge

backend 重啟後若 `連線狀態` 面板沒有 AP3 資料，可手動重建：

```powershell
.\tools\platform-tools\adb.exe forward tcp:15760 tcp:5760

$py = (Resolve-Path backend\.venv\Scripts\python.exe).Path
$script = (Resolve-Path tools\ap3_to_simulator.py).Path
$logDir = (Resolve-Path .logs).Path

Start-Process -FilePath $py `
  -ArgumentList @("-u", $script, "--websocket-url", "ws://127.0.0.1:8888/ws/gps") `
  -WorkingDirectory (Resolve-Path .).Path `
  -RedirectStandardOutput ($logDir + "\ap3_bridge.log") `
  -RedirectStandardError ($logDir + "\ap3_bridge.log.err")
```

## Raspberry Pi USRP

根目錄 `.env` 應由範本建立：

```powershell
Copy-Item .env.example .env
```

```dotenv
RASPI_HOST=<Raspberry Pi IP>
RASPI_USER=<Raspberry Pi 帳號>
RASPI_PSW=<Raspberry Pi 密碼>
RASPI_PORT=22
USRP_UPLOAD_API_URL=http://<這台電腦的區網 IPv4>:8888/api/usrp/upload-noise-csv
USRP_UPLOAD_API_URLS=http://<A laptop IPv4>:8888/api/usrp/upload-noise-csv,https://backend.simworld.website/api/usrp/upload-noise-csv
GPS_SYNC_API_URL=http://<B laptop IPv4>:8888/api/usrp/sync-gps-point
```

`USRP_UPLOAD_API_URL` 是 Raspberry Pi 停止 mission 後回傳 `noise.csv` 的目的地。必須填目前執行 backend 的電腦，且該 IPv4 必須和 Raspberry Pi 互通；不可使用 `localhost`、`127.0.0.1`、Raspberry Pi IP 或另一台電腦的舊 IP。

`USRP_UPLOAD_API_URLS` 支援多個 `noise.csv` 上傳目的地，用逗號分隔；有設定時優先於 `USRP_UPLOAD_API_URL`。A+B 同時上傳可設成 `http://<A laptop IPv4>:8888/api/usrp/upload-noise-csv,https://backend.simworld.website/api/usrp/upload-noise-csv`。

A 筆電接遙控器、B 筆電跑 backend 時，在 A 筆電設定 `GPS_SYNC_API_URL=http://<B laptop IPv4>:8888/api/usrp/sync-gps-point`。每筆 AP3/controller GPS 會即時寫到 B 筆電的 `incoming/<mission-id>/gps.csv`，同步 log 在 `incoming/<mission-id>/gps_sync.log`，也可用 `http://<B laptop IPv4>:8888/api/usrp/gps-sync/logs?mission_id=<mission-id>` 查最近 log。

```powershell
Get-NetIPAddress -AddressFamily IPv4 |
  Where-Object { $_.IPAddress -notlike '127.*' -and $_.AddressState -eq 'Preferred' } |
  Select-Object InterfaceAlias, IPAddress
```

啟動 backend 後，從 Raspberry Pi 驗證反向連線：

```bash
curl --connect-timeout 5 http://<這台電腦的區網 IPv4>:8888/docs
```

若逾時，檢查 backend 是否監聽 TCP 8888，以及 Windows 防火牆是否允許 Raspberry Pi 所在區網連入。SSH Start 成功只證明電腦可以連到 Raspberry Pi，不能證明 Stop 所需的 CSV 反向上傳可用。

Raspberry Pi 端安裝：

```bash
sudo cp tools/pi_radio_stack.sh /home/user/pi_radio_stack.sh
sudo cp tools/pi_radio_stack.service.example /etc/systemd/system/drone.service
sudo cp tools/pi_radio_stack.test.service.example /etc/systemd/system/drone_test.service
sudo systemctl daemon-reload
sudo systemctl show drone -p TimeoutStopUSec -p KillMode
```

預期顯示 `TimeoutStopUSec=20s` 與 `KillMode=control-group`。若目前 mission 正在執行，先不要覆寫或 reload 該 service；等 mission inactive 後再部署。部署後 Stop 只負責停止採樣、保存 CSV 並回報 `upload_pending`，上傳由主機背景工作或面板的 `Retry upload` 執行。

Timeout 階段：Pi 子程序 10 秒 graceful + 2 秒 force confirmation；systemd 20 秒；SSH stop command 25 秒；backend capture API 30 秒；前端 POST 35 秒。停止命令超時會顯示 `presumed_running/reconciling`，不可當作已停止；服務已確認停止但網路上傳失敗則保留 `stopped/upload_pending`。

不要把 `drone.service` 或 `drone_test.service` 設成開機自動啟動；由 `採樣控制面板` 在每次 mission 啟動時控制。

前端對應：

- `Test` 會使用 `drone_test.service`
- `USRP` 會使用 `drone.service`
- `Start USRP` 開始 USRP 干擾採樣
- `Stop USRP` 停止採樣並等待本地檔案 finalize；上傳獨立執行，不阻塞 Stop
- `Pending upload` 表示 Raspberry Pi 上的 CSV 保留，可用 `Retry upload` 重試

輸出檔：

```text
incoming/<mission-id>/gps.csv
incoming/<mission-id>/gps_sync.log
incoming/<mission-id>/noise.csv
```

## Bound Mission 實機驗收清單

以下情境需要實際 AP3、Raspberry Pi 與可寫入的 Noise upload endpoint；一般
backend/frontend 自動測試不應依賴硬體。每個情境都要記錄畫面上的
`mission_id`、兩個 child 的 Connection／Service／File／Phase，以及最後的
`capture.json`。

### 基線與正常完成

- [ ] AP3 ADB 已授權、forwarding 可用，Raspberry Pi SSH 與對應 service 可用；兩張 Device Health 都顯示 Ready。
- [ ] 開啟 Bind 後啟動 Bound Capture；確認 AP3 與 USRP 都 Running，且 mission、GPS、Noise 的 `mission_id` 相同。
- [ ] 按 Stop All；確認兩側都曾開始 stop，GPS 為 Ready、Noise 為 Uploaded，最後 Mission 顯示 Completed。
- [ ] 確認 `incoming/<mission-id>/gps.csv` 只有一個 canonical header，Noise 檔案可在 upload endpoint 取得。

### AP3 拔插與接續

- [ ] 任務 Running 時拔除 AP3，十秒後確認 GPS 顯示 Offline／Reconciling、Mission 為 Degraded，而 Noise 仍 Recording。
- [ ] 五分鐘內重新接回 AP3；確認同一 mission 自動 Resume，GPS 追加到原檔案、不重複 header、不建立新 mission。
- [ ] 維持 AP3 拔除超過五分鐘再接回；確認顯示 Resume Timeout 與 Partial GPS file available，既有 GPS rows 保留，Noise 可繼續。
- [ ] 完成 Stop All 後確認該任務不會因 AP3 後續恢復而被改寫；下一個任務的 AP3 Device Health 可回到 Ready。

### Raspberry Pi 斷線與恢復

- [ ] 任務 Running 時中斷 Raspberry Pi 網路；確認 Noise Connection 為 Offline、Service 保留 Presumed running／Reconciling，AP3 不被停止。
- [ ] 恢復 SSH 後確認系統以原 mission 讀取遠端狀態；遠端仍 Running 才回到 Running，不可自動建立新 mission 或送出 restart。
- [ ] 在遠端仍不確定時按 Stop All；確認不會顯示 Stopped／Completed，待重連後才可使用 USRP Retry Stop。

### Stop failure、重試與上傳重試

- [ ] 模擬單邊 Stop failure；確認另一側仍完成，Stop All 變成已消費，失敗 child 顯示 Retry Stop，成功 child 顯示 Disabled 的 Stopped。
- [ ] 重連必要硬體後只按失敗 child 的 Retry Stop；確認不會再次停止 sibling，成功後重新聚合為 Completed 或 Completed with Warning。
- [ ] 讓第一次 Noise upload 與 5／15／30 秒自動重試全部失敗；確認維持 Upload Pending、畫面顯示自動重試已用盡，不能提前 Completed with Warning。
- [ ] 外部網路恢復後按 Manual Retry；確認顯示執行秒數、automatic attempt 仍為 3/3，成功後 Noise Uploaded 且任務才可 Completed。

### 重啟恢復與證據留存

- [ ] 在 AP3 Resume 等待、Stop failure、以及 upload retry waiting 各階段重啟 backend；確認 `capture.json` 的 deadline、stop intent、retry attempt 與 next-attempt timestamp 仍存在。
- [ ] 重啟 frontend／重新整理頁面；確認仍顯示同一 mission 與 child 狀態，沒有重送 Stop All、Resume 或 upload job。
- [ ] 將每個情境的時間、操作、畫面截圖、`capture.json` 與 backend log 一起歸檔；硬體測試結束後再清理 runtime 產物。

## Cloudflare Tunnel

Windows PowerShell：

```powershell
.\start.ps1
```

Windows 產生的 tunnel 設定會放在：

```text
.logs/cloudflared-win.yml
```

host 對應：

```text
backend.simworld.website  -> http://localhost:8888
frontend.simworld.website -> http://localhost:5173
```

Docker compose 用：

```powershell
docker compose up --build
```

Docker 的 `cloudflared/config.yml` 目前設定：

```text
backend.simworld.website  -> http://localhost:8000
frontend.simworld.website -> http://localhost:5173
```

這是 container 內部 port，和 Windows 本機的 8888 不同。
