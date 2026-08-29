@echo off
rem Rehearsal runner: one unattended cloud arc with telemetry enabled,
rem output captured to .runtime\logs\rehearsal-<ts>.log for the video
rem storyboard (docs/video/). Detached via PowerShell Start-Process.
cd /d "%~dp0.."
if not exist .runtime\logs mkdir .runtime\logs
powershell -NoProfile -Command ^
  "$ts = Get-Date -Format yyyyMMdd-HHmmss; $p = Start-Process -FilePath 'deploy\run-cloud-arc.cmd' -WorkingDirectory '%CD%' -WindowStyle Hidden -RedirectStandardOutput ('.runtime\logs\rehearsal-' + $ts + '.log') -RedirectStandardError ('.runtime\logs\rehearsal-' + $ts + '.err.log') -PassThru; Write-Host ('rehearsal pid: ' + $p.Id); Write-Host ('log: .runtime\logs\rehearsal-' + $ts + '.log')"
