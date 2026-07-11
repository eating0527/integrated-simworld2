param(
    [string]$Serial = "58e9dd83"
)

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ScrcpyDir = Join-Path $ScriptDir "scrcpy\scrcpy-win64-v3.3.4"
$ScrcpyExe = Join-Path $ScrcpyDir "scrcpy.exe"

if (-not (Test-Path $ScrcpyExe)) {
    Write-Error "scrcpy.exe not found at $ScrcpyExe"
    exit 1
}

Start-Process -FilePath $ScrcpyExe `
    -ArgumentList "--serial", $Serial, "--window-title", "ALIGN AP3 Mirror", "--max-size", "1600", "--video-codec", "h264" `
    -WorkingDirectory $ScrcpyDir
