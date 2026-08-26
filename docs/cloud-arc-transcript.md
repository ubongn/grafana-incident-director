# Agent-vs-Cloud — arc transcript (M3)

**What this is:** a captured, unattended run of the Incident Director agent
against **Grafana Cloud** telemetry — fault injected into the simulator →
SLO alert fires in cloud Grafana → agent detects through the Grafana MCP
server → *(triangulate → diagnose → remediate-gate → report)*.

| | |
|---|---|
| Stack | <https://olivetiramisu3480.grafana.net> (Grafana Cloud, prod-eu-central-0) |
| Data plane | hosted Prometheus + Loki, fed by the keep-alive sim (`SIM_CARDINALITY=cloud`, 5 s ticks, job `hiclaw-sim`) |
| Agent | `incident-director` (Google ADK, `gemini-3.6-flash`) via **mcp-grafana** stdio, service-account token |
| Alerting | 5 SLO rules (uids `ott-*`) in folder *OTT Incidents*, datasource `prom-ott` (hosted Prom) |
| Runner | `deploy\run-cloud-arc.cmd` → `incident-director demo --scenario cdn-edge-degraded` (DEMO_MODE=1, unattended, approval gate refuses execution) |

---

## Run 1 — 2026-08-26 19:48–19:52 UTC+2 (run-20260826-195202-d6b4ff)

**Inject.** Harness POSTs the fault to the sim control API:

```
[harness] scenario 'cdn-edge-degraded' injected (sc-001); waiting for alert ott-edge-latency ...
```

**Cloud alerting does its job** (rule `ott-edge-latency`, `for: 3m`, p95 > 800 ms
— evaluated by Grafana Cloud against the sim's remote-written series):

```
    waiting for alert... firing=[] pending=[]          (t+~55 s: threshold crossed, Pending)
    waiting for alert... firing=[] pending=['ott-edge-latency']
    ...                                                (3-minute `for` window)
[harness] ott-edge-latency FIRING after 231.0s
[demo] === ALERT->PROPOSAL 60s WINDOW OPEN ===
```

**DETECT — agent reads cloud alert state through mcp-grafana** (the MCP server
logs show it connecting to `https://olivetiramisu3480.grafana.net`, listing
alert rules, per-instance states):

```
[detect] reading alert state through Grafana MCP ...
[detect] Alert 'ott-edge-latency' is currently firing due to elevated p95 latency
         on CDN edge cdn-fra1 exceeding the 800ms threshold.
         All other SLO alert rules remain normal.
```

Exactly right: one edge (cdn-fra1), one rule, everything else Normal — read
live from the cloud stack, not from the harness.

**TRIANGULATE — stopped by the model provider:**

```
[triangulate] quantifying blast radius ...
google.genai.errors.ServerError: 503 UNAVAILABLE.
{'message': 'This model is currently experiencing high demand. ...'}
=== arc run-20260826-195202-d6b4ff -> failed ===
```

## Run 2 — same day 19:59 UTC+2 (quota root cause surfaced)

```
[harness] scenario 'cdn-edge-degraded' injected (sc-002); waiting for alert ...
[harness] ott-edge-latency FIRING after 205.2s
[detect] ... 429 RESOURCE_EXHAUSTED
Quota exceeded for metric: generativelanguage.googleapis.com/generate_content_free_tier_requests
quotaId: GenerateRequestsPerDayPerProjectPerModel-FreeTier   quotaValue: 20
```

**Root cause of both failures:** the AI Studio key is free-tier —
**20 generate-requests/day/model**. Run 1's detect + retried triangulates
(and the genai SDK's internal tenacity retries on 503/429) consumed the day's
budget; Run 2 had none left. Not a code defect: the agent↔cloud plumbing is
proven end-to-end through DETECT (see above), and the alert pipeline
(sim → hosted Prom → cloud alerting → firing in 205–231 s) is fully live.

## What is proven E2E on cloud today

1. **Ingest:** sim remote-writes to hosted Prometheus + pushes to hosted Loki,
   continuously (30 metric series, log streams queryable).
2. **Alerting:** provisioned SLO rules evaluate in cloud and honor thresholds +
   `for` windows (Pending → Firing transitions observed twice, unattended).
3. **Agent DETECT via MCP:** `mcp-grafana` against the cloud stack lists rule
   states; the agent's detect phase summarized the incident correctly
   (firing edge rule, degraded edge identified, no false positives).
4. **Unattended discipline:** DEMO_MODE forces `refuse_unattended` — no
   remediation executes without a human.

## Completing the transcript (TRIANGULATE → REPORT)

The quota resets at midnight Pacific. Then, with the keep-alive sim still
running:

```powershell
deploy\run-cloud-arc.cmd            # ~6–8 min: inject → fire → full arc
```

Expected tail of a completed run (paste here after capture):

```
[harness] ott-edge-latency FIRING after ~210s
[detect] ... cdn-fra1 ... 800ms threshold ...
[triangulate] <blast radius: region(s), platform(s), fleet vs single edge>
[diagnose] <root cause + cited PromQL / Loki evidence lines>
[remediate] proposal: <playbook action> — REFUSED by approval gate (unattended demo)
[report] <postmortem markdown with evidence chain>
outcome=refused  detect->proposal=<s>s  run_id=<id>
```

> **Demo-day note:** 20 requests/day/model cannot carry ADK agent runs with
> retries. Before the recorded demo, switch to a billed key (or Vertex AI once
> the GCP project lands ~Aug 30) — `.env` `GEMINI_API_KEY` is the only knob.

---

*Captured by `hack_3` during M3-final. Raw console logs: `arc-raw.log`
(gitignored, workspace-local).*
