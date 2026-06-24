# GPS Tracker startup script for Windows PowerShell
# Usage: .\start.ps1
#        .\start.ps1 -NoTunnel
#        .\start.ps1 -NoAP3
#        .\start.ps1 -NoGpsCsv
#        .\start.ps1 -Reload

param(
    [switch]$NoTunnel,
    [switch]$NoAP3,
    [switch]$NoGpsCsv,
    [switch]$Reload,
    [switch]$CsvWatch,
    [switch]$GpsCsv,
    [string]$CsvWatchPath = "",
    [string]$CsvWatchScene = "NTPU",
    [string]$CsvDevicesFile = "",
    [string]$CsvMapType = "iss",
    [string]$GpsMissionId = "",
    [string]$GpsAltitude = "relative",
    [string]$GpsMavlinkUrl = "",
    [switch]$UsrpAutoStart,
    [string]$UsrpPiHost = "",
    [string]$UsrpPiUser = "user",
    [int]$UsrpPiPort = 22,
    [string]$UsrpSshKey = "",
    [string]$UsrpUploadApiUrl = "",
    [string]$UsrpScene = "",
    [string]$UsrpRemoteWorkDir = "/home/user/digitaltwin-modulation/USRP_transmit/noise_detect",
    [string]$UsrpRemoteStackScript = "/home/user/pi_radio_stack.sh",
    [string]$UsrpRemoteNoiseCsv = "/home/user/digitaltwin-modulation/USRP_transmit/noise_detect/noise.csv",
    [string]$UsrpRemoteUploaderScript = "/home/user/watch_and_upload_noise.py",
    [string]$UsrpRemoteUploadHelper = "/home/user/upload_noise_csv.py",
    [string]$UsrpRemotePython = "/usr/bin/python3",
    [string]$UsrpDevicesFile = ""
)

$ScriptDir   = Split-Path -Parent $MyInvocation.MyCommand.Path
$BackendDir  = Join-Path $ScriptDir "backend"
$FrontendDir = Join-Path $ScriptDir "frontend"
$LogDir      = Join-Path $ScriptDir ".logs"
$EnvFile     = Join-Path $ScriptDir ".env"
$ToolsDir    = Join-Path $ScriptDir "tools"
$IncomingDir = if ($CsvWatchPath) { $CsvWatchPath } else { Join-Path $ScriptDir "incoming" }
$MissionStateDir = Join-Path $ScriptDir ".logs"
$CurrentMissionFile = Join-Path $MissionStateDir "current_mission_id.txt"

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

function Initialize-GpsCsvTarget {
    param(
        [string]$IncomingRoot,
        [string]$MissionId
    )

    $missionDir = Join-Path $IncomingRoot $MissionId
    $gpsCsvPath = Join-Path $missionDir "gps.csv"
    New-Item -ItemType Directory -Force -Path $missionDir | Out-Null
    if (-not (Test-Path $gpsCsvPath)) {
        Set-Content -Path $gpsCsvPath -Value "time_stamp,lat,lon,alt" -Encoding ASCII
    }
    return $gpsCsvPath
}

function Resolve-LaptopIPv4 {
    $candidates = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Where-Object {
            $_.IPAddress -notlike "127.*" -and
            $_.IPAddress -notlike "169.254.*" -and
            $_.PrefixOrigin -ne "WellKnown"
        } |
        Sort-Object -Property InterfaceMetric
    return ($candidates | Select-Object -First 1 -ExpandProperty IPAddress)
}

function ConvertTo-BashDoubleQuoted {
    param([string]$Value)
    $escaped = $Value.Replace('\', '\\').Replace('"', '\"').Replace('$', '\$').Replace('`', '\`')
    return [string][char]34 + $escaped + [char]34
}

function Start-UsrpRemoteMission {
    param(
        [string]$SshExe,
        [string]$Host,
        [string]$User,
        [int]$Port,
        [string]$SshKeyPath,
        [string]$MissionId,
        [string]$Scene,
        [string]$MapType,
        [string]$ApiUrl,
        [string]$RemoteWorkDir,
        [string]$RemoteStackScript,
        [string]$RemoteNoiseCsv,
        [string]$RemoteUploaderScript,
        [string]$RemoteUploadHelper,
        [string]$RemotePython,
        [string]$DevicesFile,
        [string]$LogPath
    )

    $watcherArgs = @(
        "--noise-csv", $RemoteNoiseCsv,
        "--uploader-script", $RemoteUploadHelper,
        "--api-url", $ApiUrl,
        "--scene", $Scene,
        "--mission-id", $MissionId,
        "--map-type", $MapType,
        "--auto-simulate-last"
    )
    if ($DevicesFile) {
        $watcherArgs += @("--devices-file", $DevicesFile)
    }

    $watcherArgString = ($watcherArgs | ForEach-Object { ConvertTo-BashDoubleQuoted $_ }) -join " "
    $remoteEnv = @(
        "WORKDIR=" + (ConvertTo-BashDoubleQuoted $RemoteWorkDir),
        "NOISE_CSV=" + (ConvertTo-BashDoubleQuoted $RemoteNoiseCsv),
        "START_NOISE_LOGGER=1",
        "START_NOISE_UPLOADER=1",
        "NOISE_UPLOADER_SCRIPT=" + (ConvertTo-BashDoubleQuoted $RemoteUploaderScript),
        "NOISE_UPLOADER_ARGS=" + (ConvertTo-BashDoubleQuoted $watcherArgString),
        "PYTHON_BIN=" + (ConvertTo-BashDoubleQuoted $RemotePython)
    ) -join " "

    $remoteCommand = "nohup env $remoteEnv /bin/bash " + (ConvertTo-BashDoubleQuoted $RemoteStackScript) + " >/tmp/pi_radio_stack_${MissionId}.log 2>&1 &"
    $sshArgs = @("-p", "$Port")
    if ($SshKeyPath) {
        $sshArgs += @("-i", $SshKeyPath)
    }
    $sshArgs += @(
        "-o", "StrictHostKeyChecking=accept-new",
        "$User@$Host",
        $remoteCommand
    )

    return Start-Process -FilePath $SshExe `
        -ArgumentList $sshArgs `
        -RedirectStandardOutput $LogPath `
        -RedirectStandardError ($LogPath + ".err") `
        -NoNewWindow -PassThru
}

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
$nodeExe = (Get-Command node -ErrorAction SilentlyContinue).Source
if (-not $nodeExe) {
    Err "Missing node.exe, install Node.js and ensure it is available on PATH"
    exit 1
}
$viteScript = Join-Path $FrontendDir "node_modules\vite\bin\vite.js"
if (-not (Test-Path $viteScript)) {
    Err "Missing Vite entrypoint, run: cd frontend; npm install"
    exit 1
}

# Check environment versions
Info "Checking environment versions..."
$checkEnvScript = Join-Path $ToolsDir "check_env.py"
& $pythonExe $checkEnvScript
if ($LASTEXITCODE -ne 0) {
    Warn "Environment check reported issues. Continuing startup with the current environment."
    Warn "If startup later fails, update dependencies: cd backend; .venv\Scripts\python -m pip install -r requirements.txt"
}

if (-not (Test-Path (Join-Path $FrontendDir "node_modules"))) {
    Err "Missing node_modules, run: cd frontend; npm install"
    exit 1
}

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

$jobs = @()
$ap3BridgeJob = $null
$csvWatchJob = $null
$gpsCsvJob = $null
$ap3BridgeScript = Join-Path $ToolsDir "ap3_to_simulator.py"
$ap3BridgeLog = Join-Path $LogDir "ap3_bridge.log"
$csvWatchScript = Join-Path $ToolsDir "watch_csv_incoming.py"
$csvWatchLog = Join-Path $LogDir "csv_watch.log"
$gpsCsvScript = Join-Path $ToolsDir "ap3_to_gps_csv.py"
$gpsCsvLog = Join-Path $LogDir "ap3_gps_csv.log"
$usrpRemoteJob = $null
$usrpRemoteLog = Join-Path $LogDir "usrp_remote_start.log"
$enableGpsCsv = $GpsCsv -and -not $NoGpsCsv

if (-not $GpsMissionId) {
    $GpsMissionId = Get-Date -Format "yyyyMMdd_HHmmss"
}

New-Item -ItemType Directory -Force -Path $MissionStateDir | Out-Null
$GpsMissionId | Set-Content -Path $CurrentMissionFile -Encoding ASCII
Info "Current mission id: $GpsMissionId"
Info "   Saved to: .logs\current_mission_id.txt"

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
$backendArgs = @("-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8888")
if ($Reload) {
    $backendArgs += "--reload"
}
$backendJob = Start-Process -FilePath $pythonExe `
    -ArgumentList $backendArgs `
    -WorkingDirectory $BackendDir `
    -RedirectStandardOutput $backendLog `
    -RedirectStandardError  ($backendLog + ".err") `
    -NoNewWindow -PassThru
$jobs += $backendJob
Info "   Backend PID: $($backendJob.Id)  log: .logs\backend.log"
if ($Reload) {
    Info "   Backend reload mode: enabled"
} else {
    Info "   Backend reload mode: disabled"
}

Start-Sleep -Seconds 2

# --- Frontend ---
Info "Starting frontend (port 5173)..."
$frontendLog = Join-Path $LogDir "frontend.log"
$frontendArgs = @($viteScript, "--host", "0.0.0.0", "--port", "5173")
$frontendJob = Start-Process -FilePath $nodeExe `
    -ArgumentList $frontendArgs `
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

function Start-Ap3GpsCsvWriter {
    param(
        [string]$PythonExe,
        [string]$WriterScript,
        [string]$WorkingDir,
        [string]$LogPath,
        [string]$MissionId,
        [string]$IncomingDir,
        [string]$Altitude,
        [string]$MavlinkUrl
    )

    $writerArgs = @(
        "-u",
        $WriterScript,
        "--mission-id",
        $MissionId,
        "--incoming-dir",
        $IncomingDir,
        "--altitude",
        $Altitude
    )
    if ($MavlinkUrl) {
        $writerArgs += @("--mavlink-url", $MavlinkUrl)
    }
    return Start-Process -FilePath $PythonExe `
        -ArgumentList $writerArgs `
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

# --- AP3 GPS CSV writer ---
if ($enableGpsCsv) {
    if (Test-Path $gpsCsvScript) {
        $gpsCsvTarget = Initialize-GpsCsvTarget -IncomingRoot $IncomingDir -MissionId $GpsMissionId
        Info "Starting AP3 GPS CSV writer..."
        $gpsCsvJob = Start-Ap3GpsCsvWriter `
            -PythonExe $pythonExe `
            -WriterScript $gpsCsvScript `
            -WorkingDir $ScriptDir `
            -LogPath $gpsCsvLog `
            -MissionId $GpsMissionId `
            -IncomingDir $IncomingDir `
            -Altitude $GpsAltitude `
            -MavlinkUrl $GpsMavlinkUrl
        $jobs += $gpsCsvJob
        Info "   AP3 GPS CSV PID: $($gpsCsvJob.Id)  log: .logs\ap3_gps_csv.log"
        Info "   GPS CSV target: $gpsCsvTarget"
        if ($gpsCsvJob.HasExited) {
            Warn "AP3 GPS CSV writer exited immediately; it will be restarted by the monitor loop."
        } else {
            Info "   AP3 GPS CSV auto-restart monitor enabled"
        }
    } else {
        Warn "AP3 GPS CSV writer script not found, skipping GPS CSV worker"
    }
}

# --- CSV watch / replay worker ---
if ($CsvWatch) {
    if (Test-Path $csvWatchScript) {
        New-Item -ItemType Directory -Force -Path $IncomingDir | Out-Null
        Info "Starting CSV watch worker..."
        $csvWatchArgs = @(
            "-u",
            $csvWatchScript,
            "--watch-dir",
            $IncomingDir,
            "--python-exe",
            $pythonExe,
            "--replay-script",
            (Join-Path $ToolsDir "replay_csv_to_simulator.py"),
            "--scene",
            $CsvWatchScene,
            "--map-type",
            $CsvMapType,
            "--api-url",
            "http://127.0.0.1:8888/api/usrp/measurement",
            "--auto-simulate-last"
        )
        if ($CsvDevicesFile) {
            $csvWatchArgs += @("--devices-file", $CsvDevicesFile)
        }
        $csvWatchJob = Start-Process -FilePath $pythonExe `
            -ArgumentList $csvWatchArgs `
            -WorkingDirectory $ScriptDir `
            -RedirectStandardOutput $csvWatchLog `
            -RedirectStandardError ($csvWatchLog + ".err") `
            -NoNewWindow -PassThru
        $jobs += $csvWatchJob
        Info "   CSV watch PID: $($csvWatchJob.Id)  log: .logs\csv_watch.log"
        Info "   CSV watch dir: $IncomingDir"
    } else {
        Warn "CSV watch script not found, skipping CSV watch"
    }
}

# --- Remote USRP auto-start / upload mission ---
if ($UsrpAutoStart) {
    if (-not $UsrpPiHost) {
        Warn "UsrpAutoStart requested but UsrpPiHost is empty, skipping remote USRP startup"
    } else {
        $sshExe = (Get-Command ssh -ErrorAction SilentlyContinue).Source
        if (-not $sshExe) {
            Warn "OpenSSH client not found on PATH, skipping remote USRP startup"
        } else {
            $resolvedApiUrl = $UsrpUploadApiUrl
            if (-not $resolvedApiUrl) {
                $laptopIp = Resolve-LaptopIPv4
                if ($laptopIp) {
                    $resolvedApiUrl = "http://${laptopIp}:8888/api/usrp/upload-noise-csv"
                }
            }

            $resolvedScene = if ($UsrpScene) { $UsrpScene } else { $CsvWatchScene }
            if (-not $resolvedApiUrl) {
                Warn "Could not resolve laptop upload API URL for remote USRP startup, skipping"
            } else {
                Info "Starting remote USRP mission over SSH..."
                Info "   USRP host : $UsrpPiUser@$UsrpPiHost`:$UsrpPiPort"
                Info "   Mission   : $GpsMissionId"
                Info "   Upload API: $resolvedApiUrl"
                $usrpRemoteJob = Start-UsrpRemoteMission `
                    -SshExe $sshExe `
                    -Host $UsrpPiHost `
                    -User $UsrpPiUser `
                    -Port $UsrpPiPort `
                    -SshKeyPath $UsrpSshKey `
                    -MissionId $GpsMissionId `
                    -Scene $resolvedScene `
                    -MapType $CsvMapType `
                    -ApiUrl $resolvedApiUrl `
                    -RemoteWorkDir $UsrpRemoteWorkDir `
                    -RemoteStackScript $UsrpRemoteStackScript `
                    -RemoteNoiseCsv $UsrpRemoteNoiseCsv `
                    -RemoteUploaderScript $UsrpRemoteUploaderScript `
                    -RemoteUploadHelper $UsrpRemoteUploadHelper `
                    -RemotePython $UsrpRemotePython `
                    -DevicesFile $UsrpDevicesFile `
                    -LogPath $usrpRemoteLog
                $jobs += $usrpRemoteJob
                Info "   Remote start PID: $($usrpRemoteJob.Id)  log: .logs\usrp_remote_start.log"
            }
        }
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
if ($enableGpsCsv) {
    Write-Host "  GPS CSV  : enabled (mission: $GpsMissionId)"
}
if ($CsvWatch) {
    Write-Host "  CSV Watch: enabled ($IncomingDir)"
}
if ($UsrpAutoStart) {
    Write-Host "  USRP SSH : requested"
}
Write-Host "  Mission  : $GpsMissionId"
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
        if ($enableGpsCsv -and $gpsCsvJob) {
            if ($gpsCsvJob.HasExited) {
                Warn "AP3 GPS CSV writer exited, restarting..."
                try {
                    $jobs = @($jobs | Where-Object { $_.Id -ne $gpsCsvJob.Id })
                } catch {
                    $jobs = @($jobs)
                }
                Start-Sleep -Seconds 2
                Initialize-GpsCsvTarget -IncomingRoot $IncomingDir -MissionId $GpsMissionId | Out-Null
                $gpsCsvJob = Start-Ap3GpsCsvWriter `
                    -PythonExe $pythonExe `
                    -WriterScript $gpsCsvScript `
                    -WorkingDir $ScriptDir `
                    -LogPath $gpsCsvLog `
                    -MissionId $GpsMissionId `
                    -IncomingDir $IncomingDir `
                    -Altitude $GpsAltitude `
                    -MavlinkUrl $GpsMavlinkUrl
                $jobs += $gpsCsvJob
                Info "   AP3 GPS CSV PID: $($gpsCsvJob.Id)  log: .logs\ap3_gps_csv.log"
            }
        }
        if ($CsvWatch -and $csvWatchJob) {
            if ($csvWatchJob.HasExited) {
                Warn "CSV watch worker exited, restarting..."
                try {
                    $jobs = @($jobs | Where-Object { $_.Id -ne $csvWatchJob.Id })
                } catch {
                    $jobs = @($jobs)
                }
                Start-Sleep -Seconds 2
                $csvWatchArgs = @(
                    "-u",
                    $csvWatchScript,
                    "--watch-dir",
                    $IncomingDir,
                    "--python-exe",
                    $pythonExe,
                    "--replay-script",
                    (Join-Path $ToolsDir "replay_csv_to_simulator.py"),
                    "--scene",
                    $CsvWatchScene,
                    "--map-type",
                    $CsvMapType,
                    "--api-url",
                    "http://127.0.0.1:8888/api/usrp/measurement",
                    "--auto-simulate-last"
                )
                if ($CsvDevicesFile) {
                    $csvWatchArgs += @("--devices-file", $CsvDevicesFile)
                }
                $csvWatchJob = Start-Process -FilePath $pythonExe `
                    -ArgumentList $csvWatchArgs `
                    -WorkingDirectory $ScriptDir `
                    -RedirectStandardOutput $csvWatchLog `
                    -RedirectStandardError ($csvWatchLog + ".err") `
                    -NoNewWindow -PassThru
                $jobs += $csvWatchJob
                Info "   CSV watch PID: $($csvWatchJob.Id)  log: .logs\csv_watch.log"
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
