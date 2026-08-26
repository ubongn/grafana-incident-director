@echo off
rem Start the OTT telemetry simulator against GRAFANA CLOUD (M3 mode).
rem Node loads the repo .env natively (--env-file): cloud remote-write/Loki
rem endpoints, basic-auth usernames + GRAFANA_CLOUD_API_KEY, SIM_CARDINALITY=cloud.
rem (Replaces the old `for /f` env parsing — one stale-parse too many.)
rem One-shot cred sanity check first: node sim/verify-cloud.mjs (repo root).
cd /d "%~dp0.."
node --env-file=.env sim/src/index.js
