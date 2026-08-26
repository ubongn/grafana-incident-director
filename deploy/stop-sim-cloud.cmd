@echo off
rem Stop the detached cloud keep-alive sim started by start-sim-cloud-background.cmd.
rem Targeted: kills only the node process running sim/src/index.js (via WMIC
rem command-line match), never a blanket taskkill by image name.
powershell -NoProfile -Command ^
  "Get-CimInstance Win32_Process -Filter \"Name='node.exe'\" | Where-Object { $_.CommandLine -match 'sim[\\/]src[\\/]index\.js' } | ForEach-Object { Write-Host ('stopping pid ' + $_.ProcessId); Stop-Process -Id $_.ProcessId -Force }"
