@echo off
rem Run ONE unattended agent arc (DETECT->...->REPORT) against GRAFANA CLOUD.
rem Usage:  deploy\run-cloud-arc.cmd [scenario]        (default cdn-edge-degraded)
rem Needs:  the keep-alive sim running (deploy\start-sim-cloud-background.cmd)
rem          + staged vertex-key.json (workspace root) — the agent runs on
rem          Vertex AI (billed trial credits; no free-tier 20 req/day cap).
rem Creds are parsed from the staged grafana-cloud-creds.txt (workspace root,
rem one level above the repo) — nothing sensitive is hardcoded here.
setlocal EnableExtensions
set "SCENARIO=%~1"
if "%SCENARIO%"=="" set "SCENARIO=cdn-edge-degraded"
cd /d "%~dp0.."
set "CREDS=%~dp0..\..\grafana-cloud-creds.txt"
if not exist "%CREDS%" set "CREDS=%~dp0..\grafana-cloud-creds.txt"
for /f "usebackq tokens=1,* delims==" %%a in (`findstr /b /c:"GRAFANA_URL=" /c:"GRAFANA_SA_TOKEN=" "%CREDS%"`) do set "%%a=%%b"
if "%GRAFANA_URL%"=="" echo no GRAFANA_URL in %CREDS% & exit /b 2
set "GRAFANA_SERVICE_ACCOUNT_TOKEN=%GRAFANA_SA_TOKEN%"
set "DEMO_MODE=1"
set "SIM_CONTROL_URL=http://localhost:8790"
rem AI provider: Vertex AI (explicit here so the demo path never depends on
rem .env drift). gemini-2.5-flash is GA on Vertex us-central1 (3.6 is not).
set "AI_PROVIDER=vertex"
set "GOOGLE_CLOUD_PROJECT=agentic-cinema-506710"
set "GOOGLE_CLOUD_LOCATION=us-central1"
set "GEMINI_MODEL=gemini-2.5-flash"
set "VERTEX_KEY=%~dp0..\..\vertex-key.json"
if not exist "%VERTEX_KEY%" set "VERTEX_KEY=%~dp0..\vertex-key.json"
if exist "%VERTEX_KEY%" set "GOOGLE_APPLICATION_CREDENTIALS=%VERTEX_KEY%"
rem Gemini 3.x flash occasionally 503s ("high demand") — the phase retrier
rem rides those out; each retry is a fresh attempt. NB: free-tier AI Studio
rem keys have a per-day request quota — Vertex (this runner's path) does not.
set "PHASE_RETRIES=2"
echo agent arc against %GRAFANA_URL% (scenario %SCENARIO%, unattended, AI_PROVIDER=%AI_PROVIDER%)
pushd agent
".venv\Scripts\python.exe" -m incident_director.cli demo --scenario %SCENARIO%
set "RC=%ERRORLEVEL%"
popd
exit /b %RC%
