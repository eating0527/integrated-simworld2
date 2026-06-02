# Mission startup helper for Windows PowerShell
# Starts backend/frontend plus GPS CSV + CSV watch using one shared mission id.
# Usage:
#   .\start_mission.ps1
#   .\start_mission.ps1 -MissionId mission_20260602_test01
#   .\start_mission.ps1 -Scene NTPU -MapType iss -NoTunnel

param(
    [string]$MissionId = "",
    [string]$Scene = "NTPU",
    [ValidateSet("sinr", "iss", "tss", "cfar")]
    [string]$MapType = "iss",
    [switch]$NoTunnel,
    [switch]$NoAP3,
    [switch]$Reload,
    [string]$CsvWatchPath = "",
    [string]$DevicesFile = "",
    [string]$GpsAltitude = "relative",
    [string]$GpsMavlinkUrl = "",
    [switch]$UsrpAutoStart,
    [string]$UsrpPiHost = "",
    [string]$UsrpPiUser = "user",
    [int]$UsrpPiPort = 22,
    [string]$UsrpSshKey = "",
    [string]$UsrpUploadApiUrl = "",
    [string]$UsrpRemoteWorkDir = "/home/user/digitaltwin-modulation/USRP_transmit/noise_detect",
    [string]$UsrpRemoteStackScript = "/home/user/pi_radio_stack.sh",
    [string]$UsrpRemoteNoiseCsv = "/home/user/digitaltwin-modulation/USRP_transmit/noise_detect/noise.csv",
    [string]$UsrpRemoteUploaderScript = "/home/user/watch_and_upload_noise.py",
    [string]$UsrpRemoteUploadHelper = "/home/user/upload_noise_csv.py",
    [string]$UsrpRemotePython = "/usr/bin/python3",
    [string]$UsrpDevicesFile = ""
)

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$StartScript = Join-Path $ScriptDir "start.ps1"
$MissionFile = Join-Path $ScriptDir ".logs\current_mission_id.txt"

if (-not (Test-Path $StartScript)) {
    Write-Error "Missing start.ps1: $StartScript"
    exit 1
}

if (-not $MissionId) {
    $MissionId = "mission_{0}" -f (Get-Date -Format "yyyyMMdd_HHmmss")
}

New-Item -ItemType Directory -Force -Path (Split-Path -Parent $MissionFile) | Out-Null
$MissionId | Set-Content -Path $MissionFile -Encoding ASCII

Write-Host "[INFO]  Mission id: $MissionId" -ForegroundColor Green
Write-Host "[INFO]  Scene     : $Scene" -ForegroundColor Green
Write-Host "[INFO]  Map type  : $MapType" -ForegroundColor Green
Write-Host "[INFO]  Saved to  : .logs\\current_mission_id.txt" -ForegroundColor Green

$startArgs = @(
    "-GpsCsv",
    "-CsvWatch",
    "-GpsMissionId", $MissionId,
    "-CsvWatchScene", $Scene,
    "-CsvMapType", $MapType,
    "-GpsAltitude", $GpsAltitude
)

if ($NoTunnel) {
    $startArgs += "-NoTunnel"
}
if ($NoAP3) {
    $startArgs += "-NoAP3"
}
if ($Reload) {
    $startArgs += "-Reload"
}
if ($CsvWatchPath) {
    $startArgs += @("-CsvWatchPath", $CsvWatchPath)
}
if ($DevicesFile) {
    $startArgs += @("-CsvDevicesFile", $DevicesFile)
}
if ($GpsMavlinkUrl) {
    $startArgs += @("-GpsMavlinkUrl", $GpsMavlinkUrl)
}
if ($UsrpAutoStart) {
    $startArgs += "-UsrpAutoStart"
}
if ($UsrpPiHost) {
    $startArgs += @("-UsrpPiHost", $UsrpPiHost)
}
if ($UsrpPiUser) {
    $startArgs += @("-UsrpPiUser", $UsrpPiUser)
}
if ($UsrpPiPort) {
    $startArgs += @("-UsrpPiPort", $UsrpPiPort)
}
if ($UsrpSshKey) {
    $startArgs += @("-UsrpSshKey", $UsrpSshKey)
}
if ($UsrpUploadApiUrl) {
    $startArgs += @("-UsrpUploadApiUrl", $UsrpUploadApiUrl)
}
if ($UsrpRemoteWorkDir) {
    $startArgs += @("-UsrpRemoteWorkDir", $UsrpRemoteWorkDir)
}
if ($UsrpRemoteStackScript) {
    $startArgs += @("-UsrpRemoteStackScript", $UsrpRemoteStackScript)
}
if ($UsrpRemoteNoiseCsv) {
    $startArgs += @("-UsrpRemoteNoiseCsv", $UsrpRemoteNoiseCsv)
}
if ($UsrpRemoteUploaderScript) {
    $startArgs += @("-UsrpRemoteUploaderScript", $UsrpRemoteUploaderScript)
}
if ($UsrpRemoteUploadHelper) {
    $startArgs += @("-UsrpRemoteUploadHelper", $UsrpRemoteUploadHelper)
}
if ($UsrpRemotePython) {
    $startArgs += @("-UsrpRemotePython", $UsrpRemotePython)
}
if ($UsrpDevicesFile) {
    $startArgs += @("-UsrpDevicesFile", $UsrpDevicesFile)
}

& $StartScript @startArgs
