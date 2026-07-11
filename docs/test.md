# 測試與檢查

這份文件放測試、smoke test 與常用檢查。

## 前端

```powershell
cd frontend
npm test
npm run build
cd ..
```

`npm test` 執行 Vitest。

`npm run build` 會執行 TypeScript 檢查與 Vite build。

`npm run build` 會產生 `frontend/dist/`；它只供 build 驗證，開發伺服器使用 Vite，不需要保留這個目錄。

## 後端

```powershell
cd backend
.\.venv\Scripts\python -m unittest discover -s tests
cd ..
```

## 工具腳本

```powershell
python tools\test_pi_radio_stack.py
```

## API smoke test

建議先用本機模式啟動，避免 tunnel 與硬體副作用：

```powershell
.\start.ps1 -NoTunnel -NoAP3
```

啟動後檢查：

```powershell
Invoke-RestMethod http://127.0.0.1:8888/ping
Invoke-WebRequest http://127.0.0.1:5173/ -UseBasicParsing
Invoke-RestMethod http://127.0.0.1:8888/api/gps/devices | ConvertTo-Json -Depth 5
Invoke-RestMethod http://127.0.0.1:8888/api/scene-tasks | ConvertTo-Json -Depth 6
```

指定場景任務：

```powershell
Invoke-RestMethod http://127.0.0.1:8888/api/scene-tasks/<task_id> | ConvertTo-Json -Depth 8
Invoke-RestMethod http://127.0.0.1:8888/api/scene-tasks/<task_id>/metadata | ConvertTo-Json -Depth 8
```

## 啟動問題檢查

`start.ps1` 啟動失敗時先看：

```text
.logs/backend.log.err
.logs/frontend.log.err
.logs/tunnel.log.err
.logs/ap3_bridge.log.err
```

若只需要確認前端與後端是否存活，`/ping` 回傳 HTTP 200 且 `5173/` 回傳 HTML 即可；不需要先執行 Blender、Sionna 或 AP3 硬體流程。

確認套件存在：

```powershell
Test-Path backend\.venv
Test-Path frontend\node_modules
```

確認 port：

```powershell
Get-NetTCPConnection -LocalPort 5173,8888 -ErrorAction SilentlyContinue
```

確認 Blender：

```powershell
Test-Path "C:\Program Files\Blender Foundation\Blender 4.2\blender.exe"
```

確認 LLVM：

```powershell
Test-Path "C:\Program Files\LLVM\bin\LLVM-C.dll"
```
