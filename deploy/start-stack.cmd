@echo off
REM Start the local observability stack: Prometheus :9090, Loki :3100, Grafana :3000.
REM Binaries live under .runtime\ (installed by setup-windows.ps1). No Docker.
setlocal
cd /d "%~dp0.."
for %%I in (.) do set "REPO=%%~fI"

set "PROM_EXE=%REPO%\.runtime\prometheus\prometheus.exe"
set "LOKI_EXE=%REPO%\.runtime\loki\loki.exe"
set "GRAFANA_EXE=%REPO%\.runtime\grafana\bin\grafana.exe"

if not exist "%PROM_EXE%" echo [stack] prometheus.exe missing - run deploy\setup-windows.ps1 & exit /b 1
if not exist "%LOKI_EXE%" echo [stack] loki.exe missing - run deploy\setup-windows.ps1 & exit /b 1
if not exist "%GRAFANA_EXE%" echo [stack] grafana.exe missing - run deploy\setup-windows.ps1 & exit /b 1

md ".runtime\data\prom" ".runtime\data\grafana" ".runtime\data\grafana-plugins" ".runtime\logs" 2>nul

set "GRAFANA_DASHBOARDS_DIR=%REPO%\deploy\grafana\dashboards"
set "GF_PATHS_PROVISIONING=%REPO%\deploy\grafana\provisioning"
set "GF_PATHS_DATA=%REPO%\.runtime\data\grafana"
set "GF_PATHS_LOGS=%REPO%\.runtime\logs"
set "GF_PATHS_PLUGINS=%REPO%\.runtime\data\grafana-plugins"
set "GF_SERVER_HTTP_ADDR=127.0.0.1"

echo [stack] starting prometheus (remote-write receiver on :9090)
start "prometheus" /min cmd /c ""%PROM_EXE%" --config.file="%REPO%\deploy\prometheus\prometheus.yml" --storage.tsdb.path="%REPO%\.runtime\data\prom" --web.enable-remote-write-receiver >> "%REPO%\.runtime\logs\prometheus.log" 2>&1"

echo [stack] starting loki (:3100)
start "loki" /min cmd /c ""%LOKI_EXE%" -config.file="%REPO%\deploy\loki\loki-config.yml" >> "%REPO%\.runtime\logs\loki.log" 2>&1"

echo [stack] starting grafana (:3000, admin/admin)
start "grafana" /min cmd /c ""%GRAFANA_EXE%" server --homepath="%REPO%\.runtime\grafana" --config="%REPO%\deploy\grafana\custom.ini" >> "%REPO%\.runtime\logs\grafana.log" 2>&1"

echo.
echo [stack] up. Grafana http://localhost:3000 (admin/admin) - Prometheus :9090 - Loki :3100
echo [stack] logs in .runtime\logs\ ; stop with deploy\stop-stack.cmd
endlocal
