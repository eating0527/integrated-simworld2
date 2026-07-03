# 後端與硬體操作

這份文件放 README 不需要背的操作細節：後端、AP3 bridge、Raspberry Pi USRP、Cloudflare tunnel。

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

根目錄 `.env`：

```dotenv
RASPI_HOST=<Raspberry Pi IP>
RASPI_USER=<Raspberry Pi 帳號>
RASPI_PSW=<Raspberry Pi 密碼>
RASPI_PORT=22
USRP_UPLOAD_API_URL=http://<這台電腦的區網 IP>:8888/api/usrp/upload-noise-csv
```

Raspberry Pi 端安裝：

```bash
sudo cp tools/pi_radio_stack.sh /home/user/pi_radio_stack.sh
sudo cp tools/pi_radio_stack.service.example /etc/systemd/system/drone.service
sudo cp tools/pi_radio_stack.test.service.example /etc/systemd/system/drone_test.service
sudo systemctl daemon-reload
```

不要把 `drone.service` 或 `drone_test.service` 設成開機自動啟動；由 `採樣控制面板` 在每次 mission 啟動時控制。

前端對應：

- `Test` 會使用 `drone_test.service`
- `USRP` 會使用 `drone.service`
- `Start USRP` 開始 USRP 干擾採樣
- `Stop USRP` 停止並等待檔案 finalize、upload、verify
- `Pending upload` 表示 Raspberry Pi 上的 CSV 保留，可重試

輸出檔：

```text
incoming/<mission-id>/gps.csv
incoming/<mission-id>/noise.csv
```

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
