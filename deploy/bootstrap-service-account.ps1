# Create (or reuse) a Grafana service account for the MCP server and the
# Incident Director agent, then persist its token into .env (gitignored).
# Requires the stack to be running (deploy\start-stack.cmd).
# Uses curl.exe (Windows ships it) — Invoke-RestMethod proved flaky here.
param(
    [string]$GrafanaUrl = "http://localhost:3001",
    [string]$AdminUser = "admin",
    [string]$AdminPass = "admin",
    [string]$AccountName = "incident-director"
)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$envFile = Join-Path $repo ".env"
$auth = "${AdminUser}:${AdminPass}"

# 1. wait for grafana (max ~30s)
$ok = $false
for ($i = 0; $i -lt 15; $i++) {
    $h = & curl.exe -s -m 2 -u $auth "$GrafanaUrl/api/health" 2>$null
    if ($h -match '"version"') { $ok = $true; break }
    Start-Sleep -Seconds 2
}
if (-not $ok) { throw "grafana not reachable at $GrafanaUrl" }
Write-Host "[sa] grafana reachable"

# 2. find or create the service account
$search = & curl.exe -s -u $auth "$GrafanaUrl/api/serviceaccounts/search?query=$AccountName"
$sid = $null
try {
    $sa = ($search | ConvertFrom-Json).serviceAccounts | Where-Object { $_.name -eq $AccountName } | Select-Object -First 1
    if ($sa) { $sid = $sa.id }
} catch { }
if (-not $sid) {
    $created = & curl.exe -s -X POST -u $auth -H "Content-Type: application/json" `
        -d ('{"name":"' + $AccountName + '","role":"Admin","isDisabled":false}') `
        "$GrafanaUrl/api/serviceaccounts"
    $sid = ($created | ConvertFrom-Json).id
    Write-Host "[sa] created service account '$AccountName' (id=$sid)"
} else {
    Write-Host "[sa] reusing service account '$AccountName' (id=$sid)"
}

# 3. mint a token
$tokJson = & curl.exe -s -X POST -u $auth -H "Content-Type: application/json" `
    -d ('{"name":"mcp-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '"}') `
    "$GrafanaUrl/api/serviceaccounts/$sid/tokens"
$key = ($tokJson | ConvertFrom-Json).key
if (-not $key) { throw "token mint failed: $tokJson" }

# 4. persist into .env (create from example if missing)
if (-not (Test-Path $envFile)) {
    Copy-Item (Join-Path $repo ".env.example") $envFile
    Write-Host "[sa] created .env from template"
}
$lines = Get-Content $envFile
$lines = $lines | Where-Object { $_ -notmatch "^GRAFANA_SERVICE_ACCOUNT_TOKEN=" -and $_ -notmatch "^GRAFANA_URL=" }
$lines += "GRAFANA_SERVICE_ACCOUNT_TOKEN=$key"
$lines += "GRAFANA_URL=$GrafanaUrl"
Set-Content -Path $envFile -Value $lines -Encoding ASCII

Write-Host "[sa] token written to .env (GRAFANA_SERVICE_ACCOUNT_TOKEN)"
Write-Host "[sa] done - MCP server + agent can now authenticate."
