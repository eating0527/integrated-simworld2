# GPS Tracker startup script for Windows PowerShell
# Usage: .\start.ps1
#        .\start.ps1 --no-tunnel
#        .\start.ps1 -NoAP3

param([switch]$NoTunnel, [switch]$NoAP3)

$ScriptDir   = Split-Path -Parent $MyInvocation.MyCommand.Path
$BackendDir  = Join-Path $ScriptDir "backend"
$FrontendDir = Join-Path $ScriptDir "frontend"
$LogDir      = Join-Path $ScriptDir ".logs"
$EnvFile     = Join-Path $ScriptDir ".env"
$ToolsDir    = Join-Path $ScriptDir "tools"

# Reload PATH so winget-installed tools are visible
$env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" +
            [System.Environment]::GetEnvironmentVariable("Path","User")

# Sionna / drjit needs LLVM — set path to LLVM-C.dll
$LlvmDll = "C:\Program Files\LLVM\bin\LLVM-C.dll"
if (-not $env:DRJIT_LIBLLVM_PATH -and (Test-Path $LlvmDll)) {
    $env:DRJIT_LIBLLVM_PATH = $LlvmDll
}
if (-not $env:BLENDER_PATH) {
    foreach ($BlenderCandidate in @(
        "C:\Program Files\Blender Foundation\Blender 4.2\blender.exe",
        "C:\Program Files\Blender Foundation\Blender 4.1\blender.exe",
        "C:\Program Files\Blender Foundation\Blender 4.0\blender.exe",
        "C:\Program Files\Blender Foundation\Blender 3.6\blender.exe",
        "C:\Program Files\Blender Foundation\Blender 5.1\blender.exe",
        "C:\Program Files\Blender Foundation\Blender 5.0\blender.exe"
    )) {
        if (Test-Path $BlenderCandidate) {
            $env:BLENDER_PATH = $BlenderCandidate
            break
        }
    }
}

function Info  { param($msg) Write-Host "[INFO]  $msg" -ForegroundColor Green }
function Warn  { param($msg) Write-Host "[WARN]  $msg" -ForegroundColor Yellow }
function Err   { param($msg) Write-Host "[ERROR] $msg" -ForegroundColor Red }

function Stop-PortListeners {
    param(
        [int[]]$Ports
    )
    $listeners = Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
        Where-Object { $Ports -contains $_.LocalPort }
    $pids = $listeners | Select-Object -ExpandProperty OwningProcess -Unique
    if (-not $pids) {
        return
    }

    Warn "Found stale listeners on ports $($Ports -join ', '): $($pids -join ', '), stopping..."
    foreach ($procId in $pids) {
        try {
            Stop-Process -Id $procId -Force -ErrorAction Stop
            Info "   Stopped PID: $procId"
        }
        catch {
            Warn "   Failed to stop PID: $procId"
        }
    }
    Start-Sleep -Seconds 1
}

# Load .env
if (Test-Path $EnvFile) {
    Get-Content $EnvFile | ForEach-Object {
        if ($_ -match '^\s*([^#=]+)\s*=\s*(.+)$') {
            [System.Environment]::SetEnvironmentVariable($matches[1].Trim(), $matches[2].Trim(), "Process")
        }
    }
}

# Preflight checks
$pythonExe = Join-Path $BackendDir ".venv\Scripts\python.exe"
if (-not (Test-Path $pythonExe)) {
    Err "Missing .venv, run: cd backend; python -m venv .venv; .venv\Scripts\python -m pip install -r requirements.txt"
    exit 1
}

# Check environment versions
Info "Checking environment versions..."
$checkEnvScript = Join-Path $ToolsDir "check_env.py"
& $pythonExe $checkEnvScript
if ($LASTEXITCODE -ne 0) {
    Err "Environment check failed. Update your dependencies: cd backend; .venv\Scripts\python -m pip install -r requirements.txt"
    exit 1
}

if (-not (Test-Path (Join-Path $FrontendDir "node_modules"))) {
    Err "Missing node_modules, run: cd frontend; npm install"
    exit 1
}

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

$jobs = @()
$ap3BridgeJob = $null
$ap3BridgeScript = Join-Path $ToolsDir "ap3_to_simulator.py"
$ap3BridgeLog = Join-Path $LogDir "ap3_bridge.log"

# Ensure required ports are free before startup.
Stop-PortListeners -Ports @(5173, 8888)

# Write frontend WebSocket URL into .env.local so Vite picks it up at startup
$frontendEnvLocal = Join-Path $FrontendDir ".env.local"
if ($NoTunnel) {
    # Local dev: leave WS URL empty so frontend can use local WS/API settings.
    Set-Content $frontendEnvLocal "VITE_WS_URL="
} else {
    # Tunnel mode: connect directly to backend cloudflare subdomain
    Set-Content $frontendEnvLocal "VITE_WS_URL=wss://backend.simworld.website"
}

# --- Backend ---
Info "Starting backend (port 8888)..."
$backendLog = Join-Path $LogDir "backend.log"
# Pass DRJIT_LIBLLVM_PATH explicitly so sionna can find LLVM-C.dll
$drjitEnv = if ($env:DRJIT_LIBLLVM_PATH) { "set `"DRJIT_LIBLLVM_PATH=$env:DRJIT_LIBLLVM_PATH`" && " } else { "" }
$backendCmd = "`"$pythonExe`" -m uvicorn app.main:app --host 0.0.0.0 --port 8888 --reload"
$backendJob = Start-Process -FilePath "cmd.exe" `
    -ArgumentList "/c","${drjitEnv}cd /d `"$BackendDir`" && $backendCmd" `
    -RedirectStandardOutput $backendLog `
    -RedirectStandardError  ($backendLog + ".err") `
    -NoNewWindow -PassThru
$jobs += $backendJob
Info "   Backend PID: $($backendJob.Id)  log: .logs\backend.log"

Start-Sleep -Seconds 2

# --- Frontend ---
Info "Starting frontend (port 5173)..."
$frontendLog = Join-Path $LogDir "frontend.log"
$frontendJob = Start-Process -FilePath "cmd.exe" `
    -ArgumentList "/c","npm run dev" `
    -WorkingDirectory $FrontendDir `
    -RedirectStandardOutput $frontendLog `
    -RedirectStandardError  ($frontendLog + ".err") `
    -NoNewWindow -PassThru
$jobs += $frontendJob
Info "   Frontend PID: $($frontendJob.Id)  log: .logs\frontend.log"

# --- Cloudflare Tunnel ---
if (-not $NoTunnel) {
    $cfBin = Get-Command cloudflared -ErrorAction SilentlyContinue
    if ($cfBin) {
        Info "Starting Cloudflare Tunnel..."
        $token = [System.Environment]::GetEnvironmentVariable("CLOUDFLARED_TOKEN","Process")
        $tunnelLog = Join-Path $LogDir "tunnel.log"

        # Generate a Windows-compatible config with correct credential path and ports
        $credFile = Join-Path $env:USERPROFILE ".cloudflared\c85697e6-ff3d-426e-b689-1de63c3f3338.json"
        $winConfigPath = Join-Path $LogDir "cloudflared-win.yml"
        @"
tunnel: c85697e6-ff3d-426e-b689-1de63c3f3338
credentials-file: $credFile
protocol: http2

ingress:
  - hostname: backend.simworld.website
    service: http://localhost:8888
  - hostname: frontend.simworld.website
    service: http://localhost:5173
  - service: http_status:404
"@ | Set-Content $winConfigPath -Encoding UTF8

        if ($token) {
            $tunnelJob = Start-Process -FilePath $cfBin.Source `
                -ArgumentList "tunnel","--protocol","http2","run","--token",$token `
                -RedirectStandardOutput $tunnelLog `
                -RedirectStandardError  ($tunnelLog + ".err") `
                -NoNewWindow -PassThru
        } else {
            $tunnelJob = Start-Process -FilePath $cfBin.Source `
                -ArgumentList "tunnel","--config",$winConfigPath,"run" `
                -RedirectStandardOutput $tunnelLog `
                -RedirectStandardError  ($tunnelLog + ".err") `
                -NoNewWindow -PassThru
        }
        $jobs += $tunnelJob
        Info "   Tunnel PID: $($tunnelJob.Id)  log: .logs\tunnel.log"
    } else {
        Warn "cloudflared not found, skipping tunnel"
    }
}

# --- ALIGN AP3 MAVLink bridge ---
function Start-Ap3Bridge {
    param(
        [string]$PythonExe,
        [string]$BridgeScript,
        [string]$WebsocketUrl,
        [string]$WorkingDir,
        [string]$LogPath
    )

    $bridgeArgs = @("-u", $BridgeScript, "--websocket-url", $WebsocketUrl)
    return Start-Process -FilePath $PythonExe `
        -ArgumentList $bridgeArgs `
        -WorkingDirectory $WorkingDir `
        -RedirectStandardOutput $LogPath `
        -RedirectStandardError  ($LogPath + ".err") `
        -NoNewWindow -PassThru
}

if (-not $NoAP3) {
    $adbExe = Join-Path $ToolsDir "platform-tools\adb.exe"
    if ((Test-Path $adbExe) -and (Test-Path $ap3BridgeScript)) {
        Info "Starting ALIGN AP3 telemetry bridge..."
        $ap3BridgeJob = Start-Ap3Bridge `
            -PythonExe $pythonExe `
            -BridgeScript $ap3BridgeScript `
            -WebsocketUrl "ws://127.0.0.1:8888/ws/gps" `
            -WorkingDir $ScriptDir `
            -LogPath $ap3BridgeLog
        $jobs += $ap3BridgeJob
        Info "   AP3 bridge PID: $($ap3BridgeJob.Id)  log: .logs\ap3_bridge.log"
        try {
            & $adbExe forward tcp:15760 tcp:5760 | Out-Null
            Info "   AP3 MAVLink via USB ADB forward: tcp:127.0.0.1:15760"
        } catch {
            Warn "Initial ADB forward failed; the bridge will keep waiting and retrying."
        }
        if ($ap3BridgeJob.HasExited) {
            Warn "AP3 bridge exited immediately; it will be restarted by the monitor loop."
        } else {
            Info "   AP3 bridge auto-restart monitor enabled"
        }
    } else {
        Warn "ADB or AP3 bridge script not found, skipping AP3 bridge"
    }
}

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  Frontend : http://localhost:5173"
if (-not $NoTunnel) {
    Write-Host "  Public   : https://frontend.simworld.website"
}
if (-not $NoAP3) {
    Write-Host "  AP3 GPS  : bridge auto-start enabled"
}
Write-Host "  Press Ctrl+C to stop all services"
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""

# Tail logs
try {
    while ($true) {
        Start-Sleep -Seconds 3
        if (Test-Path $backendLog) {
            $lines = Get-Content $backendLog -Tail 3
            if ($lines) { $lines | ForEach-Object { Write-Host "[backend] $_" } }
        }
        if (-not $NoAP3 -and $ap3BridgeJob) {
            if ($ap3BridgeJob.HasExited) {
                Warn "AP3 bridge exited, restarting..."
                try {
                    $jobs = @($jobs | Where-Object { $_.Id -ne $ap3BridgeJob.Id })
                } catch {
                    $jobs = @($jobs)
                }
                Start-Sleep -Seconds 2
                $ap3BridgeJob = Start-Ap3Bridge `
                    -PythonExe $pythonExe `
                    -BridgeScript $ap3BridgeScript `
                    -WebsocketUrl "ws://127.0.0.1:8888/ws/gps" `
                    -WorkingDir $ScriptDir `
                    -LogPath $ap3BridgeLog
                $jobs += $ap3BridgeJob
                Info "   AP3 bridge PID: $($ap3BridgeJob.Id)  log: .logs\ap3_bridge.log"
            }
        }
    }
} finally {
    Info "Stopping all services..."
    $jobs | ForEach-Object {
        if (-not $_.HasExited) { $_.Kill() }
    }
    Info "All stopped."
}
