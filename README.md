# Integrated Sim World

整合即時 GPS、3D 場景、地圖選點建模、照片上傳、Sionna 模擬與 USRP 採樣控制的前端操作平台。

## 目錄

- [Production 入口](#production-入口)
- [從零開始建立專案](#從零開始建立專案)
- [安裝套件](#安裝套件)
- [設定變數](#設定變數)
- [Cloudflare Tunnel](#cloudflare-tunnel)
- [啟動](#啟動)
- [前端操作](#前端操作)
- [其他文件](#其他文件)

## Production 入口

- Frontend: <https://frontend.simworld.website>
- Backend: <https://backend.simworld.website>
- Backend docs: <https://backend.simworld.website/docs>

本機啟動後的預設入口：

- Frontend: <http://localhost:5173>
- Backend: <http://localhost:8888>
- Backend docs: <http://localhost:8888/docs>

## 從零開始建立專案

第一次建立：

```powershell
git clone https://github.com/eating0527/integrated-simworld2.git
cd integrated-simworld2
```

已經有資料夾時更新：

```powershell
git pull --ff-only
```

## 安裝套件

必要工具：

- Git
- Python 3.12+
- Node.js 18+，建議 20+
- Blender 4.2 LTS
- Blosm: <https://prochitecture.gumroad.com/l/blender-osm>
- Mitsuba: <https://github.com/mitsuba-renderer/mitsuba-blender>
- LLVM，Windows 執行 Sionna 時需要 `C:\Program Files\LLVM\bin\LLVM-C.dll`
- cloudflared，production tunnel 需要
- Android platform-tools / ADB，AP3 / M4P TOP USB 定位需要

安裝後端套件：

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\python -m pip install --upgrade pip
.\.venv\Scripts\python -m pip install -r requirements.txt
cd ..
```

安裝前端套件：

```powershell
cd frontend
npm install
if (Test-Path .env.example) { Copy-Item .env.example .env -Force }
cd ..
```

安裝 LLVM：

```powershell
winget install --id LLVM.LLVM --exact --accept-package-agreements --accept-source-agreements
```

## 設定變數

第一次建立專案時，先從範本建立根目錄 `.env`：

```powershell
Copy-Item .env.example .env
```

再編輯 `.env`。密碼與 token 只放在本機，不要放到 `frontend/.env`，也不要提交。

```dotenv
RASPI_HOST=<Raspberry Pi IP，例如 192.168.1.50>
RASPI_USER=<Raspberry Pi 帳號，例如 user>
RASPI_PSW=<Raspberry Pi 密碼>
RASPI_PORT=22
USRP_UPLOAD_API_URL=http://<這台電腦的區網 IPv4>:8888/api/usrp/upload-noise-csv
USRP_UPLOAD_API_URLS=http://<A laptop IPv4>:8888/api/usrp/upload-noise-csv,https://backend.simworld.website/api/usrp/upload-noise-csv
GPS_SYNC_API_URL=http://<B laptop IPv4>:8888/api/usrp/sync-gps-point
GPS_SYNC_DEVICE_ID=align-m4p-top-aircraft
GPS_SYNC_DEVICE_NAME=M4P TOP Aircraft

# 有 Cloudflare token 時才填
CLOUDFLARED_TOKEN=<Cloudflare tunnel token>
```

`USRP_UPLOAD_API_URL` 是 Raspberry Pi 在 mission 停止時回傳 `noise.csv` 的位址，必須使用**目前執行 backend 這台電腦**的 Wi-Fi 或有線網路 IPv4。不要填 `localhost`、`127.0.0.1`、Raspberry Pi IP，或從另一台電腦複製過來的舊 IP。

`USRP_UPLOAD_API_URLS` 可設定多個 `noise.csv` 上傳目的地，用逗號分隔；有設定時會優先於 `USRP_UPLOAD_API_URL`。例如 A 筆電本機 backend 加上 B 筆電 Cloudflare backend：`http://<A laptop IPv4>:8888/api/usrp/upload-noise-csv,https://backend.simworld.website/api/usrp/upload-noise-csv`。

如果是 A 筆電接遙控器、B 筆電跑 backend，把 A 筆電的 `GPS_SYNC_API_URL` 設成 `http://<B laptop IPv4>:8888/api/usrp/sync-gps-point`。A 筆電每收到一筆 AP3/controller GPS，就會同步 append 到 B 筆電的 `incoming/<mission-id>/gps.csv`，同時透過既有 GPS WebSocket 廣播給前端，並寫入 `incoming/<mission-id>/gps_sync.log`。可用 `http://<B laptop IPv4>:8888/api/usrp/gps-sync/logs?mission_id=<mission-id>` 看最近同步 log。

Windows 可用以下命令找出和 Raspberry Pi 位於同一區網的 IPv4：

```powershell
Get-NetIPAddress -AddressFamily IPv4 |
  Where-Object { $_.IPAddress -notlike '127.*' -and $_.AddressState -eq 'Preferred' } |
  Select-Object InterfaceAlias, IPAddress
```

啟動 backend 後，應在 Raspberry Pi 上確認回傳位址可連線：

```bash
curl --connect-timeout 5 http://<這台電腦的區網 IPv4>:8888/docs
```

如果逾時，先確認 backend 已啟動，並允許 Windows 防火牆接收該區網介面的 TCP 8888 連線。Start mission 只會測試「電腦連到 Raspberry Pi」，不代表 Stop mission 所需的「Raspberry Pi 連回電腦」也可用。

前端環境檔位於 `frontend/.env`。本機預設可使用：

```dotenv
VITE_WS_URL=ws://localhost:5173/ws/gps
VITE_API_URL=
VITE_ORIGIN_LAT=24.942349
VITE_ORIGIN_LON=121.367164
VITE_ORIGIN_ALT=0
VITE_NTPU_ORIGIN_LAT=24.943476
VITE_NTPU_ORIGIN_LON=121.370054
VITE_NTPU_ORIGIN_ALT=0
VITE_SCENE_SCALE=1
```

Production tunnel 啟動時，`start.ps1` 會自動把 `frontend/.env.local` 寫成：

```dotenv
VITE_WS_URL=wss://backend.simworld.website
```

## Cloudflare Tunnel

Windows PowerShell 啟動 production tunnel 時使用：

```powershell
.\start.ps1
```

`start.ps1` 會產生 `.logs/cloudflared-win.yml`，內容會把：

- `backend.simworld.website` 指到 `http://localhost:8888`
- `frontend.simworld.website` 指到 `http://localhost:5173`

cloudflared 認證二選一：

- 在目前 PowerShell session 設定 `CLOUDFLARED_TOKEN`
- 或把 credentials JSON 放在 `%USERPROFILE%\.cloudflared\c85697e6-ff3d-426e-b689-1de63c3f3338.json`

Docker compose 使用 `cloudflared/config.yml`，其中 backend container 走 `http://localhost:8000`，不要拿來覆蓋 Windows 的 8888 設定。

## 啟動

Production tunnel：

```powershell
.\start.ps1
```

只開本機，不開 tunnel：

```powershell
.\start.ps1 -NoTunnel
```

不啟動 AP3 bridge：

```powershell
.\start.ps1 -NoAP3
```

同時寫入 AP3 GPS CSV：

```powershell
.\start.ps1 -GpsCsv
```

啟動成功後終端機會顯示：

```text
Frontend : http://localhost:5173
Public   : https://frontend.simworld.website
AP3 GPS  : bridge auto-start enabled
```

## 前端操作

### 地圖建模

1. 開啟 `http://localhost:5173` 或 `https://frontend.simworld.website`。
2. 畫面會前往 `建模選點`。
3. 在地圖上點選位置。
4. 確認面板顯示：
   - `Latitude`
   - `Longitude`
   - `Generation Zoom`: `18 (fixed)`
   - `Place`
5. 按 `送出 Blender 任務並返回 React`。
6. 按鈕流程會依序顯示 `確認地圖中...`、`送出選點並建立任務中...`。
7. 若沒有自動返回，按 `手動返回 React 頁面`。

### GPS 與照片

- `連線狀態` 面板會顯示 `已連線`、`連線中` 或 `連線失敗`。
- 手機端會出現拍照上傳按鈕；上傳時顯示 `上傳中…`，完成後顯示 `上傳成功`。
- 電腦端會顯示 `照片` 歷史清單。

### 裝置設定

在 `裝置設定` 面板的位置區域，可用右側 icon 在 GPS 經緯度與 xyz 座標間切換。預設為 GPS 模式，TX、RX、Jammer 都支援變更位置。

- 座標先保留在欄位草稿，按 `套用位置` 後才更新裝置。
- 切換模式會從目前已套用的 xyz 位置重新計算，捨棄未套用草稿，避免兩種座標不同步。
- GPS 與 xyz 位置都必須落在目前 scene extent 內；超出範圍時無法套用。
- RX 套用位置後會同步既有 UAV 位置狀態。

### 採樣控制面板

面板名稱是 `採樣控制面板`。

`裝置綁定`：

- `關閉`：`無人機 GPS 採樣` 與 `USRP 干擾採樣` 分開控制。
- `啟用`：兩邊都 Ready 時，用 `Start Bound Capture` 同步開始。

`無人機 GPS 採樣`：

- 狀態欄位：`Connection`、`Service`、`File`
- 按鈕：`Start UAV`、`Stop UAV`

`USRP 干擾採樣`：

- 模式：`Test`、`USRP`
- 按鈕：`Start USRP`、`Stop USRP`
- 綁定模式按鈕：`Start Bound Capture`、`Stop All`
- 常見狀態值：`Ready`、`Offline`、`Running`、`Presumed running`、`Pending upload`、`Uploaded`

### 無線模擬與干擾源定位

按 `📡 無線模擬` 開啟 `無線通道模擬` 面板。面板有 8 個子面板：

- `SINR Map`：產生訊號強度覆蓋圖，可調 `SINR Min (dB)`、`SINR Max (dB)`、`Cell Size (m)` 與 `Samples / TX`。
- `CFR`：產生通道頻率響應，可選 `QPSK` 或 `16QAM`，也可打開 `進階設定`。
- `Doppler`：產生都卜勒分析圖。
- `Channel IR`：產生通道脈衝響應圖。
- `ISS Map`：產生 ISS 訊號地圖。
- `TSS Map`：產生 TSS 訊號地圖。
- `ISS+CFAR Map`：在 ISS 地圖上標示 CFAR 偵測結果。
- `ISS_UNET`：用 `Sim`、`GPS` 或 `Noise with GPS` 產生 ISS_UNET 重建結果。

`ISS_UNET` 的重建干擾地圖流程：

1. 在 `Mode` 選 `Sim`、`GPS` 或 `Noise with GPS`。
2. 選 `Resolution`：`1 m/px (512)`、`2 m/px (256)` 或 `4 m/px (128)`。
3. 若選 `GPS`，上傳 `GPS CSV`；若選 `Noise with GPS`，同時上傳 `GPS CSV` 與 `Noise CSV`。
4. 視需要開啟 `OS-CFAR` 與 `Building Mask`。
5. 按 `開始計算` 後，結果區可看 `干擾地圖`；`OS-CFAR` 啟用後可切到 `CFAR` 查看干擾源定位。
6. `Noise with GPS` 可另外按 `產生統計資料`，檢查 GPS 與 Noise 對齊後的統計圖。

## 其他文件

- [後端與硬體操作](docs/ops.md)
- [技術細節](docs/tech.md)
- [測試與檢查](docs/test.md)
- [開發筆記](docs/dev.md)
