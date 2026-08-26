@echo off
rem Keep-alive sim against Grafana Cloud, DETACHED (survives the console).
rem Used for demo readiness: panels + alert rules stay fed with live data
rem after the operator/agent session that started it is gone.
rem
rem How: PowerShell Start-Process launches node in its own hidden process
rem (no console window, parent process exits, node keeps running).
rem Logs: sim-cloud.log / sim-cloud.err.log at the repo root.
rem Stop: deploy\stop-sim-cloud.cmd
cd /d "%~dp0.."
powershell -NoProfile -Command ^
  "Start-Process -FilePath 'node' -ArgumentList '--env-file=.env','sim/src/index.js' -WorkingDirectory '%CD%' -WindowStyle Hidden -RedirectStandardOutput 'sim-cloud.log' -RedirectStandardError 'sim-cloud.err.log' -PassThru | ForEach-Object { Write-Host ('sim pid: ' + $_.Id) }"
