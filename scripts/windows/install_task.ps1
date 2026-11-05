# Registers the "QICK Analyzer" scheduled task on the Windows lab PC: run_server.cmd at boot, as SYSTEM (no
# login or stored password needed), with no time limit. Run once in an administrator PowerShell, from the repo:
#   powershell -ExecutionPolicy Bypass -File scripts\windows\install_task.ps1
# Then: Start-ScheduledTask "QICK Analyzer" (or reboot). Stop it with Stop-ScheduledTask "QICK Analyzer";
# remove it with Unregister-ScheduledTask "QICK Analyzer".
$cmd = Join-Path $PSScriptRoot "run_server.cmd"
$action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"$cmd`""
$trigger = New-ScheduledTaskTrigger -AtStartup
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 999 `
    -RestartInterval (New-TimeSpan -Minutes 1) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
Register-ScheduledTask -TaskName "QICK Analyzer" -Action $action -Trigger $trigger -Settings $settings `
    -Principal $principal -Description "QICK Analyzer web app on port 8090 (scripts\windows\run_server.cmd)" -Force
