@echo off
REM Stop the local observability stack binaries started by start-stack.cmd.
taskkill /IM grafana.exe /F 2>nul && echo [stack] grafana stopped
taskkill /IM loki.exe /F 2>nul && echo [stack] loki stopped
taskkill /IM prometheus.exe /F 2>nul && echo [stack] prometheus stopped
echo [stack] down.
