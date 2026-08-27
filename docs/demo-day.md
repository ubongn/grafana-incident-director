# Demo-Day Runbook — Ubong (video ~Sep 7, judges browse after)

> Everything you need to record the video and leave the demo browsing-ready.
> Target: a ~3-min recording of one live agent arc + the public dashboard,
> with the sim kept alive afterwards so judges see live data when they click.

**Links**

| What | URL | Auth |
|---|---|---|
| **Public dashboard** (show this on camera; judges get this link) | <https://olivetiramisu3480.grafana.net/public-dashboards/10d81eda6d4d40058f07ad8b8b0f126a> | none — Public share (read-only) |
| Internal stack | <https://olivetiramisu3480.grafana.net> | login |
| Full dashboard | <https://olivetiramisu3480.grafana.net/d/ott-streaming-ops> | login |
| Captured E2E transcript (backup if live demo fails) | [`docs/cloud-arc-transcript.md`](cloud-arc-transcript.md) | — |

---

## 1. Pre-roll checklist (run ~30 min before recording)

| # | Check | Command | Pass looks like |
|---|---|---|---|
| 1 | **Keep-alive sim alive** (feeds hosted Prometheus/Loki) | `node deploy\cloud-check.mjs` | `PROM ott_sessions_active{job="hiclaw-sim"} -> HTTP 200 | 30 series` + `LOKI ... streams 3` with a **fresh ts** (seconds old) |
| 2 | **Grafana Cloud reachable** | open the public dashboard URL in an incognito window | 15 panels render, latency lines moving — no login prompt |
| 3 | **Vertex probe OK** (model path healthy) | `python scripts\vertex_probe.py` | REST `200` for `gemini-2.5-flash` (the agent's model) |
| 4 | creds staged | `grafana-cloud-creds.txt` + `vertex-key.json` one level above the repo (workspace root) | both files exist (never committed) |

**Status as of 2026-08-27 ~11:54 UTC (verified post-M3):** sim alive — 30 series, Loki tick 11:53:56Z; full E2E arc already captured unattended (see transcript).

### If the sim is dead (check 1 fails: 0 series / stale ts)

```powershell
deploy\start-sim-cloud-background.cmd   # detached (survives console), logs -> sim-cloud.log
```

Wait ~30 s, re-run `node deploy\cloud-check.mjs` until the series count returns and ts is fresh.
Stop it (only when needed) with `deploy\stop-sim-cloud.cmd` — it targets the sim by command line; **never** blanket-`taskkill node` (that would take down unrelated processes).

---

## 2. The one-command live arc

With the sim alive, this is the entire demo (run it in a visible terminal — the phase lines are your camera material):

```powershell
deploy\run-cloud-arc.cmd
```

The script is self-contained: it parses Grafana creds from the staged file, pins the **Vertex AI** env (`AI_PROVIDER=vertex`, `gemini-2.5-flash` @ `us-central1` — no free-tier quota), sets `DEMO_MODE=1` (unattended gate always refuses) and `PHASE_RETRIES=2`.

### Expected timeline (from the captured run `run-20260827-110301-4b65af`)

| Event | Wall time | What you'll see |
|---|---|---|
| Fault injected (`cdn-edge-degraded`, edge `cdn-fra1`) | t0 | arc banner prints |
| Cloud alert `ott-edge-latency` goes **FIRING** | **~201 s** after inject | rule p95 > 800 ms with `for: 3m` — the brew (see timing tip) |
| **DETECT** | **6.8 s** | `[detect]` isolates the one firing rule from 5 SLO rules |
| **TRIANGULATE** | **23.4 s** | `[triangulate]` scope=regional: cdn-fra1 latency ~2216 ms, 5xx 3.1%, playback errors 1.8% |
| **DIAGNOSE** | **5.5 s** | `[diagnose]` upstream fetch timeouts → 504s, conf 0.9 |
| **REMEDIATE** | **3.6 s** | `[remediate]` proposal: `drain_cdn_edge {"edge": "cdn-fra1"}` |
| **GATE** | ~0 s | `[gate] approved=False decided_by=mode:refuse_unattended` — the safety story |
| **REPORT** | **7.6 s** | `[report]` annotation posted + verification query |

**Totals: 47 s DETECT→REPORT** (39.4 s detect→proposal), every phase first-attempt, outcome `denied` — the gate holding is the *expected* result, say that on camera.

---

## 3. Timing tip — the 3.3-minute brew

The alert needs **~3.3 min** to fire after injection (`for: 3m` + eval interval). Two ways to handle it:

1. **Inject first, narrate while it brews** (recommended): launch `run-cloud-arc.cmd`, immediately cut to the dashboard tour / intro narration (~3 min of material: what the panels show, the 5 SLO rules, the agent's runbook). By the time you're done talking, the terminal shows FIRING and the phases start rolling.
2. **Or edit a timelapse**: record the full run, cut the brew down to a few seconds in post, keep all 8 phase lines intact.

---

## 4. What to show on camera (suggested order)

1. **Public dashboard** (incognito!) — 15 panels, live sim data moving. Punchline: *"this exact URL is in the README — no login, judges, go click it."*
2. **Agent terminal** — the one command, then the phase lines: `[detect] → [triangulate] → [diagnose] → [remediate] → [gate] → [report]`. Read the TRIANGULATE line out loud (real ms/percentages from cloud PromQL).
3. **The gate refusal** — *"unattended mode: execution requires an interactive human approval."* The agent diagnosed in 47 s and **still didn't touch production** — that's the framework-enforced approval gate.
4. **The annotation landing** — after `[report]`, refresh the public dashboard: the incident annotation the agent posted is now on the panel timeline. The loop closes *inside Grafana*.
5. Optional closer: `docs/cloud-arc-transcript.md` + the hash-chained `audit/audit-*.jsonl` — the evidence chain for skeptics.

---

## 5. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `429 RESOURCE_EXHAUSTED` from Gemini | running on the **AI Studio free-tier key** (20 req/day) | Use `deploy\run-cloud-arc.cmd` (pins Vertex) or set `AI_PROVIDER=vertex` in `.env`. Vertex = billed trial credits, no cap |
| Gemini `503 high demand` | transient | `PHASE_RETRIES=2` already rides it out; just rerun the arc |
| cloud-check: 0 series / stale ts | keep-alive sim died | `deploy\start-sim-cloud-background.cmd`, wait 30 s, re-check (§1) |
| Alert never fires (no FIRING after ~4 min) | sim dead (metrics flat) or rule missing | verify sim (§1); rules are idempotently provisioned by `deploy/provision_cloud.py` |
| Local fallback stack needed (cloud unreachable) | — | `deploy\start-stack.cmd` (Grafana :3001 / Prometheus :9090 / Loki :3100, binaries already downloaded; first-ever boot downloads them, ~5 min — do that **before** recording day). Cold-resume note: local Grafana state persists between runs, but give it ~30 s after start before opening dashboards |
| Vertex probe non-200 | stale key / project env | `python scripts\vertex_probe.py`; key staged at workspace root as `vertex-key.json`, project `agentic-cinema-506710` us-central1 |
| Recording runs long | the 3.3-min brew | see §3 — inject first, narrate over it |

---

## 6. After recording (judges browse later)

- Keep the sim alive: **do not** run `stop-sim-cloud.cmd` after the video — the public dashboard should keep showing live data while judges click through.
- If the machine reboots before judging: rerun `deploy\start-sim-cloud-background.cmd` + `node deploy\cloud-check.mjs` (§1).
- The captured transcript `docs/cloud-arc-transcript.md` stays in the repo as the permanent E2E record.
