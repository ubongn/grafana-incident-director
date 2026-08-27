# Agent-vs-Cloud Incident Arc — Complete E2E Transcript

> **The full unattended arc against Grafana Cloud, start to finish.**
> Run `run-20260827-110301-4b65af` · 2026-08-27 09:03 UTC · unattended (`DEMO_MODE=1`)
> Model: **`gemini-2.5-flash` on Vertex AI** (`agentic-cinema-506710` / `us-central1`, service-account ADC) — billed trial credits, **no free-tier quota cap**. (Earlier arcs died at TRIANGULATE on the AI Studio free tier's 20 req/day limit; provider seam `AI_PROVIDER=vertex` in `.env` / `deploy\run-cloud-arc.cmd` fixed that — the run below needed zero retries.)
> Evidence: hash-chained audit trail in `audit/audit-20260827.jsonl` (SHA-256 linked list, tamper-evident); console capture `arc-raw.log`.

## Stack under test

| Piece | Endpoint |
|---|---|
| Grafana Cloud | `https://olivetiramisu3480.grafana.net` (dashboard `ott-streaming-ops`, 15 panels) |
| Hosted Prometheus | datasources uid `prom-ott` (remote-write from local sim) |
| Hosted Loki | datasources uid `loki-ott` |
| Agent hands | Grafana MCP server (`mcp-grafana` v1.2.0, stdio, service-account token) — **the only path to the stack** |
| Agent brain | Gemini on Vertex AI (one ADK `LlmAgent` per phase, phase-narrowed MCP tool filters) |

## Timeline

| t (UTC) | Phase | Wall time | MCP tool calls | What happened |
|---|---|---|---|---|
| 08:59:40 (t−200.9s) | INJECT | — | — | Harness injects scenario `cdn-edge-degraded` (`sc-003`) into the local sim → metrics degrade in hosted Prometheus |
| 08:59:40→09:03:01 | ALERT | **200.9s** | — | Cloud rule `ott-edge-latency` (p95 > 800ms, `for: 3m`) goes Pending → **FIRING** — rule evaluation honored exactly as configured |
| 09:03:01 | ARC START | — | — | Trigger: firing alert. `DEMO_MODE=1` → gate forced to `refuse_unattended` |
| 09:03:03–09:03:08 | DETECT | **6.78s** | `alerting_manage_rules` | Reads live alert state: *"The 'ott-edge-latency' alert rule is firing… All other SLO alerts are normal."* — single degraded edge isolated from 5 SLO rules |
| 09:03:08–09:03:31 | TRIANGULATE | **23.44s** | `get_dashboard_panel_queries` + `query_prometheus` ×8 | Pulls panel PromQL from the cloud dashboard, runs comparison queries: **scope=regional** — eu-west only, `cdn-fra1` latency **2215.78 ms**, 5xx **3.08%**, playback errors **1.76%**; all other regions/origins/transcoders normal → hypothesis 1 confirmed: *CDN edge degraded* |
| 09:03:32–09:03:37 | DIAGNOSE | **5.53s** | `query_loki_logs` | Cloud Loki evidence: upstream fetch timeouts → 504s at `cdn-fra1` → **conf 0.9** |
| 09:03:37–09:03:40 | REMEDIATE | **3.56s** | *(none — by design)* | Proposes `execute / drain_cdn_edge {"edge": "cdn-fra1"}` — never executes |
| 09:03:40 | GATE | ~0s | — | **`approved=false`** · `decided_by=mode:refuse_unattended` — framework-enforced human gate, unattended runs never touch the world |
| 09:03:40–09:03:48 | REPORT | **7.56s** | `create_annotation`, `query_prometheus` | Posts incident annotation to the cloud dashboard, then verifies with PromQL — honestly reports latency **remains high because remediation was denied** (correct!) |

**Totals:** alert `200.9s` after injection (cloud eval window) · DETECT→REPORT **47s** wall · alert→proposal **39.36s** · every phase first-attempt (`attempts: 1`), zero LLM retries, zero quota errors · outcome `denied` — the *expected* unattended result (gate held).

## Verbatim phase outputs

```text
=== incident arc run-20260827-110301-4b65af (trigger: alert) ===
[detect]    The 'ott-edge-latency' alert rule is firing, indicating high CDN edge
            latency. All other SLO alerts are normal.
[triangulate] scope=regional: The incident is localized to the eu-west region,
            specifically impacting the cdn-fra1 edge. This edge is experiencing
            high latency (2215.78ms) and an elevated 5xx error ratio (3.08%),
            leading to a higher playback error rate in the eu-west region
            (1.76%). All other regions, origins, and transcoders are operating
            normally. This aligns with hypothesis 1: CDN edge degraded.
[diagnose]  CDN edge cdn-fra1 is experiencing upstream fetch timeouts, leading
            to 504 errors and elevated latency. This is causing playback errors
            in the eu-west region. (conf=0.9)
[remediate] proposal: execute / drain_cdn_edge {'edge': 'cdn-fra1'}
            (39.36s detect->proposal)
[gate]      approved=False decided_by=mode:refuse_unattended
            "unattended mode: execution requires an interactive human approval"
[report]    Incident annotation posted to Grafana; verification query confirms
            edge latency remains degraded (as expected — remediation denied).
=== outcome: denied (gate held — no unattended execution) ===
```

## Remediation proposal (from the audit chain)

> "The diagnosis and triangulation clearly indicate that the cdn-fra1 edge is degraded, exhibiting high latency (2215.78ms) and a significant 5xx error ratio (3.08%) due to upstream fetch timeouts. This directly impacts the eu-west region's playback error rate (1.76%). Draining this edge will route traffic away from the problematic CDN node, mitigating the impact on users in the eu-west region." — `execute / drain_cdn_edge {"edge": "cdn-fra1"}`

## Tool-call accounting (compliance evidence)

Every stack interaction below went through the **Grafana MCP server** at runtime — no direct datasource HTTP in the agent:

| Phase | Tool calls (in order) |
|---|---|
| detect | `alerting_manage_rules` |
| triangulate | `get_dashboard_panel_queries`, `query_prometheus` (×8 pairs) |
| diagnose | `query_loki_logs` |
| remediate | — (tool-less by design: proposes, never executes) |
| report | `create_annotation`, `query_prometheus` |

## Reproduce

```powershell
deploy\start-sim-cloud-background.cmd   # keep-alive sim -> hosted Prometheus/Loki
deploy\run-cloud-arc.cmd                # one full unattended arc (Vertex AI)
```

## History

- **2026-08-26** — arcs 1–2 vs cloud: DETECT proven E2E, then killed by AI Studio free-tier 429 (`RESOURCE_EXHAUSTED`, 20 req/day/model). Root-caused and documented in the prior revision of this file.
- **2026-08-27** — provider seam switched to Vertex AI (`AI_PROVIDER=vertex`, gemini-2.5-flash GA there; 3.6 is AI-Studio-only). **Complete arc above — the quota blocker is gone.**
