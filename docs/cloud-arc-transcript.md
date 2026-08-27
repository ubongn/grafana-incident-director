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

## Live-demo re-run — run-20260827-163604-9fe96b (2026-08-27 14:31 UTC, manager-witnessed)

> Second full cloud arc, same scenario class (`cdn-edge-degraded`), executed live while the public judge dashboard was being watched. Pre-flight verified green before launch: sim alive (30 series, fresh Loki tick), public dashboard HTTP 200, `vertex_probe` 200 on `gemini-2.5-flash`, all 5 SLO rules Normal, `.env` seam `AI_PROVIDER=vertex`. An **independent MCP poller** (own stdio session to `mcp-grafana` v1.2.0, `alerting_manage_rules` operation=list every 15 s) ran alongside the harness to confirm alert state transitions without trusting the harness's word.

| t (UTC) | Phase | Wall time | MCP tools | What happened |
|---|---|---|---|---|
| 14:31:58 | LAUNCH | — | — | `deploy\run-cloud-arc.cmd` (Vertex pinned: `AI_PROVIDER=vertex`, `gemini-2.5-flash` @ us-central1, `DEMO_MODE=1`) |
| ~14:32:02 | INJECT | — | — | Scenario `cdn-edge-degraded` (`sc-004`) injected; poller + harness timers aligned |
| 14:32:59 | ALERT Pending | t+60 s | (poller) | Rule crosses threshold → `pending` (independent MCP poll) |
| **14:36:01** | **ALERT FIRING** | **241.7 s** | (poller) | **FIRING confirmed via MCP t+241.9 s — harness measured inject→FIRING 241.7 s** (~4 min brew; M3 was 200.9 s — rule eval cadence phase) |
| 14:36:04 | ARC START | — | — | Trigger: firing alert; gate pre-forced to `refuse_unattended` |
| | DETECT | **4.56 s** | `alerting_manage_rules` | Isolates the one firing rule out of 5 |
| | TRIANGULATE | **13.67 s** | `get_dashboard_panel_queries` ×5, `query_prometheus` | **scope=regional eu-west**: `cdn-fra1` latency **1620.58 ms**, 5xx **3.75 %**, playback errors **2.05 %**; everything else healthy |
| | DIAGNOSE | **15.52 s** | `find_error_pattern_logs` ×2, `query_loki_logs` | Upstream fetch timeouts → 504s → **conf 0.9** |
| | REMEDIATE | **3.62 s** | *(none — by design)* | Full `drain_cdn_edge {"edge": "cdn-fra1"}` proposal with effect/risk/rollback/rationale |
| 14:36:41 | GATE | ~0 s | — | **`approved=false` · `decided_by=mode:refuse_unattended`** — gate held, no execution |
| | REPORT | **8.41 s** | `create_annotation`, `query_prometheus` | **Annotation id=2 posted at 14:36:45Z**; verification query honestly reports latency **2025 ms persists** (remediation denied) |

**Totals:** DETECT→proposal **37.43 s** · DETECT→REPORT **≈45.9 s** · every phase `attempts: 1` · outcome `denied` (expected). Two transient MCP tool errors (`"now"` time-unmarshal; one 5 s tool timeout) were absorbed by tool-level retry — **zero phase retries**. Audit chain after the run: **OK — 18 entries, chain intact** (`audit/audit-20260827.jsonl`; this run is hash-chained onto the morning's M3 run in the same file).

**Downstream symptom (the "playback error spike" class):** Grafana's own state annotations show `ott-playback-errors` (SLO, `for: 2m`) went **Pending at 14:36:20Z** — the CDN fault propagated to player errors exactly as the runbook says, and resolved with the scenario (`ott-edge-latency` back to **Normal at 14:37:00Z**, all 5 rules Normal post-arc, sim untouched and still feeding).

**Data footprint (what the public dashboard shows):** hosted Prometheus (the panels' datasource) shows `cdn-fra1` p95 ~**2259 ms at 14:34:00Z** vs ~100 ms baseline, recovering at 14:37:00Z — the spike is inside the public dashboard's default 30-min window.

**Public-dashboard annotation caveat (verified live):** Grafana 13 public shares strip the annotations layer — the shared model ships without the `annotations` field and `/api/public/dashboards/{uid}/annotations` returns `[]` anonymously (both annotations, 24 h window). The agent's annotation (id=2, tags `incident-director`, author `sa-1-mcp-agent`, dashboard `ott-streaming-ops`) is real and visible on the **internal** dashboard + via the annotations API; on the public share, the arc is visible through its live data footprint. `docs/demo-day.md` shot list updated accordingly.

## History

- **2026-08-26** — arcs 1–2 vs cloud: DETECT proven E2E, then killed by AI Studio free-tier 429 (`RESOURCE_EXHAUSTED`, 20 req/day/model). Root-caused and documented in the prior revision of this file.
- **2026-08-27** — provider seam switched to Vertex AI (`AI_PROVIDER=vertex`, gemini-2.5-flash GA there; 3.6 is AI-Studio-only). **Complete arc above — the quota blocker is gone.**
- **2026-08-27 (14:31 UTC)** — **live-demo re-run** (section above): same scenario, manager-witnessed while the public dashboard was being watched. FIRING 241.7 s (independently confirmed via MCP poller), DETECT→REPORT ≈45.9 s, gate held, annotation id=2, audit chain OK (18 entries). Found + documented the public-share annotation limitation.
