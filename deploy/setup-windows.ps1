# Idempotent local stack setup (Windows, no Docker).
# Downloads Grafana / Prometheus / Loki binaries into .runtime\ and extracts
# them. Safe to re-run; existing downloads and extractions are kept.
param(
    [string]$GrafanaVersion = "13.2.0",
    [string]$PrometheusVersion = "3.14.0",
    [string]$LokiVersion = "3.7.6"
)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$dl = Join-Path $repo ".runtime\downloads"
$bin = Join-Path $repo ".runtime"
New-Item -ItemType Directory -Force $dl | Out-Null

function Get-Zip([string]$name, [string]$url) {
    $dest = Join-Path $dl $name
    if (Test-Path $dest) {
        Write-Host "[setup] $name already downloaded"
    } else {
        Write-Host "[setup] downloading $url"
        Invoke-WebRequest -Uri $url -OutFile $dest
    }
    return $dest
}

# --- Grafana OSS (windows zip) ---
$grafanaZip = Get-Zip "grafana.zip" `
    "https://dl.grafana.com/oss/release/grafana-$GrafanaVersion.windows-amd64.zip"
if (-not (Test-Path "$bin\grafana\bin\grafana.exe")) {
    Write-Host "[setup] extracting grafana"
    $tmp = "$bin\_gx"
    Expand-Archive -Path $grafanaZip -DestinationPath $tmp -Force
    Move-Item "$tmp\grafana-$GrafanaVersion" "$bin\grafana" -Force
    Remove-Item $tmp -Recurse -Force
}

# --- Prometheus (windows zip) ---
$promZip = Get-Zip "prometheus.zip" `
    "https://github.com/prometheus/prometheus/releases/download/v$PrometheusVersion/prometheus-$PrometheusVersion.windows-amd64.zip"
if (-not (Test-Path "$bin\prometheus\prometheus.exe")) {
    Write-Host "[setup] extracting prometheus"
    $tmp = "$bin\_px"
    Expand-Archive -Path $promZip -DestinationPath $tmp -Force
    Move-Item "$tmp\prometheus-$PrometheusVersion.windows-amd64" "$bin\prometheus" -Force
    Remove-Item $tmp -Recurse -Force
}

# --- Loki (windows exe zip) ---
$lokiZip = Get-Zip "loki.zip" `
    "https://github.com/grafana/loki/releases/download/v$LokiVersion/loki-windows-amd64.exe.zip"
if (-not (Test-Path "$bin\loki\loki.exe")) {
    Write-Host "[setup] extracting loki"
    New-Item -ItemType Directory -Force "$bin\loki" | Out-Null
    Expand-Archive -Path $lokiZip -DestinationPath "$bin\loki" -Force
    if (Test-Path "$bin\loki\loki-windows-amd64.exe") {
        Move-Item "$bin\loki\loki-windows-amd64.exe" "$bin\loki\loki.exe" -Force
    }
}

Write-Host "[setup] done. Binaries:"
Write-Host "  grafana    $bin\grafana\bin\grafana.exe"
Write-Host "  prometheus $bin\prometheus\prometheus.exe"
Write-Host "  loki       $bin\loki\loki.exe"
Write-Host "[setup] next: deploy\start-stack.cmd, then deploy\bootstrap-service-account.ps1"
