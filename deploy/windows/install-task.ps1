<#
.SYNOPSIS
    Registers (or removes) a Windows Scheduled Task that starts Hoerbuch-Generator Web Studio
    at user logon / startup and automatically restarts it if it crashes.

.EXAMPLE
    # Install autostart bound to localhost:7865
    powershell -ExecutionPolicy Bypass -File .\deploy\windows\install-task.ps1

.EXAMPLE
    # Install autostart reachable across your private LAN and open Windows Firewall port 7865
    powershell -ExecutionPolicy Bypass -File .\deploy\windows\install-task.ps1 -BindHost 0.0.0.0 -OpenFirewall

.EXAMPLE
    # Remove the scheduled task and firewall rule
    powershell -ExecutionPolicy Bypass -File .\deploy\windows\install-task.ps1 -Uninstall
#>
[CmdletBinding()]
param(
    [string]$TaskName = "HoerbuchGeneratorStudio",
    [string]$BindHost = "127.0.0.1",
    [int]$Port = 7865,
    [switch]$AtStartup,
    [switch]$OpenFirewall,
    [switch]$Uninstall
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$RuleName = "Hoerbuch-Generator Studio ($Port)"

if ($Uninstall) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Remove-NetFirewallRule -DisplayName $RuleName -ErrorAction SilentlyContinue
    Write-Host "Removed task '$TaskName' and firewall rule '$RuleName' (if present)."
    exit 0
}

# Prefer portable embedded Python, then local .venv, then global python
$Candidates = @(
    (Join-Path $RepoRoot "python\python.exe"),
    (Join-Path $RepoRoot ".venv\Scripts\pythonw.exe"),
    (Join-Path $RepoRoot ".venv\Scripts\python.exe")
)
$PythonExe = $Candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $PythonExe) {
    $cmd = Get-Command pythonw -ErrorAction SilentlyContinue
    if (-not $cmd) { $cmd = Get-Command python -ErrorAction SilentlyContinue }
    if (-not $cmd) { throw "Python executable not found. Install Python 3.12 or create .venv first." }
    $PythonExe = $cmd.Source
}

$WebPy = Join-Path $RepoRoot "web.py"
$Args = "-I `"$WebPy`" --host $BindHost --port $Port --no-browser"

$Action = New-ScheduledTaskAction -Execute $PythonExe -Argument $Args -WorkingDirectory $RepoRoot
$Trigger = if ($AtStartup) { New-ScheduledTaskTrigger -AtStartup } else { New-ScheduledTaskTrigger -AtLogOn }
$Settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit (New-TimeSpan -Days 0)

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $Trigger `
    -Settings $Settings `
    -Description "Runs Hoerbuch-Generator Web Studio (http://${BindHost}:${Port}) in the background." `
    -Force | Out-Null

Start-ScheduledTask -TaskName $TaskName
Write-Host "Registered and started Scheduled Task '$TaskName' using $PythonExe"
Write-Host "Listening at http://${BindHost}:${Port}"

if ($OpenFirewall) {
    Remove-NetFirewallRule -DisplayName $RuleName -ErrorAction SilentlyContinue
    New-NetFirewallRule `
        -DisplayName $RuleName `
        -Direction Inbound `
        -Protocol TCP `
        -LocalPort $Port `
        -Action Allow `
        -Profile Private | Out-Null
    Write-Host "Opened TCP port $Port on Private firewall profile."
}
