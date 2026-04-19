# GPS Tracker startup script for Windows PowerShell
# Usage: .\start.ps1
#        .\start.ps1 --no-tunnel

param([switch]$NoTunnel)

$ScriptDir   = Split-Path -Parent $MyInvocation.MyCommand.Path
$BackendDir  = Join-Path $ScriptDir "backend"
$FrontendDir = Join-Path $ScriptDir "frontend"
$LogDir      = Join-Path $ScriptDir ".logs"
$EnvFile     = Join-Path $ScriptDir ".env"

# Reload PATH so winget-installed tools are visible
$env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" +
            [System.Environment]::GetEnvironmentVariable("Path","User")

# Sionna / drjit needs LLVM — set path to LLVM-C.dll
$LlvmDll = "C:\Program Files\LLVM\bin\LLVM-C.dll"
if (-not $env:DRJIT_LIBLLVM_PATH -and (Test-Path $LlvmDll)) {
    $env:DRJIT_LIBLLVM_PATH = $LlvmDll
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
$uvicorn = Join-Path $BackendDir ".venv\Scripts\uvicorn.exe"
if (-not (Test-Path $uvicorn)) {
    Err "Missing .venv, run: cd backend; python -m venv .venv; .venv\Scripts\pip install -r requirements.txt"
    exit 1
}
if (-not (Test-Path (Join-Path $FrontendDir "node_modules"))) {
    Err "Missing node_modules, run: cd frontend; npm install"
    exit 1
}

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

$jobs = @()

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
$pythonExe = Join-Path $BackendDir ".venv\Scripts\python.exe"
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

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  Frontend : http://localhost:5173"
if (-not $NoTunnel) {
    Write-Host "  Public   : https://frontend.simworld.website"
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
    }
} finally {
    Info "Stopping all services..."
    $jobs | ForEach-Object {
        if (-not $_.HasExited) { $_.Kill() }
    }
    Info "All stopped."
}
