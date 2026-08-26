# Create (or reuse) a Grafana service account for the MCP server and the
# Incident Director agent, then persist its token into .env (gitignored).
# Requires the stack to be running (deploy\start-stack.cmd) and first-login
# admin/admin to still be active.
param(
    [string]$GrafanaUrl = "http://localhost:3001",
    [string]$AdminUser = "admin",
    [string]$AdminPass = "admin",
    [string]$AccountName = "incident-director"
)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$envFile = Join-Path $repo ".env"

$pair = "${AdminUser}:${AdminPass}"
$basic = [Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes($pair))
$h = @{ Authorization = "Basic $basic"; "Content-Type" = "application/json" }

# 1. wait for grafana
for ($i = 0; $i -lt 30; $i++) {
    try {
        Invoke-RestMethod -Uri "$GrafanaUrl/api/health" -TimeoutSec 2 | Out-Null
        break
    } catch { Start-Sleep -Seconds 1 }
}

# 2. find or create the service account
$sa = $null
try {
    $search = Invoke-RestMethod -Uri "$GrafanaUrl/api/serviceaccounts/search?query=$AccountName" -Headers $h
    $sa = $search.serviceAccounts | Where-Object { $_.name -eq $AccountName } | Select-Object -First 1
} catch { }
if (-not $sa) {
    $sa = Invoke-RestMethod -Method Post -Uri "$GrafanaUrl/api/serviceaccounts" -Headers $h `
        -Body (@{ name = $AccountName; role = "Admin"; isDisabled = $false } | ConvertTo-Json)
    Write-Host "[sa] created service account '$AccountName' (id=$($sa.id))"
} else {
    Write-Host "[sa] reusing service account '$AccountName' (id=$($sa.id))"
}

# 3. mint a token
$tok = Invoke-RestMethod -Method Post -Uri "$GrafanaUrl/api/serviceaccounts/$($sa.id)/tokens" -Headers $h `
    -Body (@{ name = "mcp-$(Get-Date -Format 'yyyyMMdd-HHmmss')" } | ConvertTo-Json)

# 4. persist into .env (create from example if missing)
if (-not (Test-Path $envFile)) {
    Copy-Item (Join-Path $repo ".env.example") $envFile
    Write-Host "[sa] created .env from template"
}
$lines = Get-Content $envFile
$lines = $lines | Where-Object { $_ -notmatch "^GRAFANA_SERVICE_ACCOUNT_TOKEN=" -and $_ -notmatch "^GRAFANA_URL=" }
$lines += "GRAFANA_SERVICE_ACCOUNT_TOKEN=$($tok.key)"
$lines += "GRAFANA_URL=$GrafanaUrl"
Set-Content -Path $envFile -Value $lines -Encoding ASCII

Write-Host "[sa] token written to .env (GRAFANA_SERVICE_ACCOUNT_TOKEN)"
Write-Host "[sa] done - MCP server + agent can now authenticate."
