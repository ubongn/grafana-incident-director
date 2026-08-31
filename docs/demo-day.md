# Demo-Day Runbook — Ubong (record ~Sep 5–7 · submission Sep 9)

> Everything you need to record the ≤3:00 video and leave the demo browsing-ready
> for judges. The timed script is [`video-script.md`](video-script.md); the capture
> plan is [`video/shot-list.md`](video/shot-list.md). This file is the operator
> runbook: pre-flight, window choreography, exactly which panels to show when, and
> the honesty rules that keep the video DQ-proof.
>
> **Canonical run for all quoted numbers: `run-20260827-163604-9fe96b`**
> (manager-witnessed 2026-08-27 14:31–14:37 UTC — full evidence in
> [`cloud-arc-transcript.md`](cloud-arc-transcript.md)).

**Links**

| What | URL | Auth |
|---|---|---|
| **Public dashboard** (Beats 1, 3, 13 — judges get this link) | <https://olivetiramisu3480.grafana.net/public-dashboards/10d81eda6d4d40058f07ad8b8b0f126a> | none — Public share (read-only) |
| Internal stack | <https://olivetiramisu3480.grafana.net> | login |
| Full ops dashboard (annotation shot — Beat 11) | <https://olivetiramisu3480.grafana.net/d/ott-streaming-ops> | login |
| Agent Observability dashboard (Beat 12) | <https://olivetiramisu3480.grafana.net/d/agent-observability> | login |
| Captured E2E transcript (backup if live demo fails) | [`docs/cloud-arc-transcript.md`](cloud-arc-transcript.md) | — |

---

## 1. Pre-roll checklist (run ~30 min before recording)

| # | Check | Command | Pass looks like |
|---|---|---|---|
| 1 | **Keep-alive sim alive** (feeds hosted Prometheus/Loki) | `node deploy\cloud-check.mjs` | `PROM ott_sessions_active{job="hiclaw-sim"} -> HTTP 200 \| 30 series` + `LOKI ... streams 3` with a **fresh ts** (seconds old) |
| 2 | **Grafana Cloud reachable** | open the public dashboard URL in an **incognito** window | 15 panels render, latency lines moving — no login prompt |
| 3 | **Vertex probe OK** (model path healthy) | `python scripts\vertex_probe.py` (repo root, repo venv is `agent\.venv`) | REST `200` for `gemini-2.5-flash` |
| 4 | **Agent telemetry self-test** (Beat 12 material) | `python scripts\telemetry_selftest.py` | `OK: self-test series queryable` |
| 5 | creds staged | `grafana-cloud-creds.txt` + `vertex-key.json` one level above the repo (workspace root) | both files exist (never committed) |
| 6 | no scenarios active | `curl.exe http://localhost:8790/scenarios` | `"active":[]` |

**Status as of 2026-08-27 (last verified):** sim alive — 30 series; two complete
cloud arcs captured (11:03 unattended + 14:31 manager-witnessed); audit chain OK
(18 entries). Timings below are the witnessed run; brew can land 200–245 s.

### If the sim is dead (check 1 fails: 0 series / stale ts)

```powershell
deploy\start-sim-cloud-background.cmd   # detached (survives console), logs -> sim-cloud.log
```

Wait ~30 s, re-run `node deploy\cloud-check.mjs` until the series count returns and
ts is fresh. Stop it (only when needed) with `deploy\stop-sim-cloud.cmd` — it
targets the sim by command line; **never** blanket-`taskkill node` (shared host —
that would take down other agents' servers on :3000).

---

## 2. Windows & Alt+Tab choreography

Set up **three windows before pressing record**, pinned in this Z-order so every
cut is one Alt+Tab away (Alt+Tab always cycles to the *previous* window — with
three windows, double-Alt+Tab cycles to the third):

| Slot | Window | Used for beats |
|---|---|---|
| **W1** | Chrome **incognito** — public dashboard URL, light theme, zoom 110% | 1, 3, 13 |
| **W2** | Chrome **normal** (logged in to Grafana) — parked on Alerting → Alert rules; keep a second tab open on `/d/ott-streaming-ops` and a third on `/d/agent-observability` | 4, 8, 11, 12 |
| **W3** | Windows Terminal — light profile, repo root, `cls`'d, ~100 cols, Cascadia Mono 16 pt | 2, 4, 6–11 |

**The choreography per movement** (matches `video-script.md` beats):

| Beats | Action | Keystrokes |
|---|---|---|
| 1 → 2 | public dash → terminal | `Alt+Tab` (W1→W3), type command |
| 2 → 3 | terminal brew → public dash timelapse | `Alt+Tab` (W3→W1) |
| 3 → 4 | public dash → alert rules (W2) | `Alt+Tab Tab` (W1→W2) |
| 4 → 6 | alert rules → terminal phases | `Alt+Tab` (W2→W3) |
| 7 (PiP) | terminal stays fullscreen; the dash clip is a **pickup shot** edited in | — |
| 8 → terminal | Loki lines (W2 tab: Explore) → back to terminal | `Alt+Tab` |
| 11 | terminal → internal dashboard annotation | `Alt+Tab Tab` (W3→W2, switch tab) |
| 12 | internal dash → agent-observability | same window, switch tab |
| 13 | → public dash (recovered) | `Alt+Tab Tab` (W2→W1) |

Rules: never more than two taps; never touch the mouse to switch windows on
camera (it reads as fumbling); if you miss a cut, keep rolling and redo the cut in
post — the terminal take (Shot A) is the only thing that must be continuous.

---

## 3. The one-command live arc (Shot A — start recording first)

```bat
deploy\run-cloud-arc.cmd
```

Self-contained: parses Grafana creds from the staged file, pins **Vertex AI**
(`AI_PROVIDER=vertex`, `gemini-2.5-flash` @ `us-central1`), sets `DEMO_MODE=1`
(gate always refuses unattended) and `PHASE_RETRIES=2`. It injects the fault
itself — the exact HTTP call under the hood (`agent/incident_director/sim.py:50`,
form printed by `sim/src/index.js:100`):

```bat
curl.exe -X POST http://localhost:8790/scenarios/start -H "Content-Type: application/json" -d "{\"name\":\"cdn-edge-degraded\"}"
```

### Expected timeline (canonical: run-20260827-163604-9fe96b)

| Event | Wall time | What you'll see |
|---|---|---|
| Fault injected (`cdn-edge-degraded`, slot sc-004, edge `cdn-fra1`) | t0 | `[harness] scenario 'cdn-edge-degraded' injected …; waiting for alert ott-edge-latency ...` |
| `ott-edge-latency` goes **Pending** | t+60 s | poller/Alerting UI shows pending |
| `ott-edge-latency` goes **FIRING** | **241.7 s** after inject | `[harness] ott-edge-latency FIRING after ~242s` (~4 min brew — see §6) |
| **DETECT** | **4.56 s** | `[detect]` isolates the one firing rule from 5 SLO rules |
| **TRIANGULATE** | **13.67 s** | `[triangulate]` scope=regional: cdn-fra1 **1620.58 ms**, 5xx **3.75%**, eu-west playback errors **2.05%** |
| **DIAGNOSE** | **15.52 s** | `[diagnose]` upstream fetch timeouts → 504s, **conf 0.9** |
| **REMEDIATE** | **3.62 s** | `[remediate]` proposal: `drain_cdn_edge {"edge": "cdn-fra1"}` + effect/risk/rollback/rationale |
| **GATE** | ~0 s | `[gate] approved=False decided_by=mode:refuse_unattended` — **the hero line** |
| **REPORT** | **8.41 s** | `[report]` annotation id=2 posted + verification query (latency ~2025 ms persists — honestly) |
| **Totals** | **37.43 s** detect→proposal · **≈46 s** (45.78 s) detect→report | every phase `attempts: 1`; outcome `denied` = expected |

Downstream proof the fault was real: `ott-playback-errors` went Pending 14:36:20Z,
auto-recovered 14:37:00Z; all 5 rules Normal post-arc; sim untouched.

---

## 4. What's on screen per beat (panel cheat-sheet)

| Beat | Window | Screen content | Grafana surface |
|---|---|---|---|
| 1 | W1 incognito | 15 panels healthy; "Active sessions ~2.1M" | **public dashboard** |
| 2 | W3 terminal | the one command + inject line | — |
| 3 | W1 incognito | **"CDN edge latency p95 by edge"** — cdn-fra1 ramp to ~2,260 ms @14:34Z vs ~100 ms baseline; **"Playback error rate by region"** — eu-west ticks up | **public dashboard** (the arc is visible here via its data footprint) |
| 4 | W2 Alerting | rule `ott-edge-latency` Pending→**Firing** (red); then W3 FIRING line | internal (Alerting UI) |
| 5 | cut-in | `docs/architecture.svg` pan: sim → Prom/Loki → **MCP** → agents → **policy gate** → **action ledger** | — |
| 6 | W3 terminal | `[detect]` + MCP tag `alerting_manage_rules` | via MCP |
| 7 | W3 + PiP | `[triangulate]`; PiP = public dash edge-latency panel | **public dashboard** |
| 8 | W3 + cut | `[diagnose]`; cut = W2 Explore → Loki `{job="hiclaw-sim"} |= "upstream_fetch_timeout"` — 2–3 `504` lines at cdn-fra1 | internal (Explore) |
| 9 | W3 terminal | full proposal block | — |
| 10 | W3 terminal | `[gate] approved=False …` — hold 2 s, nothing else on screen | — |
| 11 | W3 → W2 | `[report]`; then **internal** `/d/ott-streaming-ops` — annotation flag (tag `incident-director`) at 14:36:45Z; overlay tally ≈46 s + audit 18 entries OK | **internal dashboard (annotations render ONLY here)** |
| 12 | W2 tab | `/d/agent-observability`: phase durations, detect→proposal 37.43 s, tokens, est. spend, gate decision denied | internal |
| 13 | W1 incognito | recovered/healthy public dash + closing card overlay | **public dashboard** |

**Public dashboard panels to know by name** (15 panels; the money panels):
"Active sessions" (hero stat) · "CDN edge latency p95 by edge" (the incident) ·
"Playback error rate by region" (the symptom) · "Origin 5xx ratio" /
"Transcoder lag" (the normals that prove scoping).

**Internal-only surfaces** (login required — never claim these on the public
link): alert rules UI, Explore/Loki, annotations layer, agent-observability.

---

## 5. Honesty notes (DQ-proofing — read before narrating)

1. **Public shares strip annotations (verified live 08-27).** Grafana 13 public
   dashboards ship without the annotations layer; the public annotations endpoint
   returns `[]` anonymously. The agent's annotation (id=2, tags
   `incident-director`) is real and visible on the **internal** dashboard and via
   the annotations API. **On camera:** show the annotation on the internal
   dashboard; for the public link, say "the arc is visible through its data
   footprint — the latency spike" — never "and there's the annotation on the
   public dashboard."
2. **Outcome `denied` is the point.** Say it: the gate holding is the designed
   behavior of an unattended run, not a failure.
3. **Numbers discipline.** Narration reads only numbers visible in the terminal
   take. Canonical values are from run-20260827-163604-9fe96b; if the recorded
   take differs, update overlays + narration everywhere (shot-list edit checklist).
4. **No eval scores unless the artifact exists.** Only quote a matrix score if
   `evals/report.md` is committed at recording time; otherwise describe the
   harness design ("graded matrix incl. a no-action trap") without a number.
5. **No secrets in frame.** Fresh terminal, `cls` first; no `.env`, no tokens, no
   scrollback with creds; incognito window has no cookies to leak.
6. **Fictional IP only.** StreamFiction everywhere; no real brands/logos.

---

## 6. Timing tip — the ~4-minute brew

The alert needs **~4 min** to fire after inject (`for: 3m` + eval cadence;
witnessed 241.7 s, morning run 200.9 s). Two ways to handle it:

1. **Inject first, narrate while it brews** (recommended): the moment Shot A's
   inject line prints, do Beats 1, 3, 5 pickups (dashboard tour, architecture
   cut-in, setup narration). By the time you're done, FIRING lands.
2. **Or edit a timelapse**: compress the `waiting for alert...` lines to ~4 s in
   post, keep every phase line intact and ordered.

---

## 7. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `429 RESOURCE_EXHAUSTED` from Gemini | running on the **AI Studio free-tier key** (20 req/day) | Use `deploy\run-cloud-arc.cmd` (pins Vertex) or `AI_PROVIDER=vertex` in `.env`. Vertex = billed trial credits, no cap |
| Gemini `503 high demand` | transient | `PHASE_RETRIES=2` rides it out; rerun the arc |
| cloud-check: 0 series / stale ts | keep-alive sim died | `deploy\start-sim-cloud-background.cmd`, wait 30 s, re-check (§1) |
| Alert never fires (no FIRING after ~4.5 min) | sim dead (metrics flat) or rule missing | verify sim (§1); rules idempotently provisioned by `deploy/provision_cloud.py` |
| Missed the Firing-state shot (Beat 4) | window is only t+60…t+300 | rerun the arc; a Pending-state capture is also honest |
| Local fallback stack needed (cloud unreachable) | — | `deploy\start-stack.cmd` (Grafana :3001 / Prometheus :9090 / Loki :3100). **Port 3000 is other agents' — never touch.** First-ever boot downloads binaries (~5 min) — do that before recording day |
| Vertex probe non-200 | stale key / project env | key staged at workspace root `vertex-key.json`, project `agentic-cinema-506710`, us-central1 |
| Recording runs long | the ~4-min brew | see §6 |

---

## 8. After recording (judges browse later)

- Keep the sim alive: **do not** run `stop-sim-cloud.cmd` after the video — the
  public dashboard should keep showing live data while judges click through
  (re-verify daily: `node deploy\cloud-check.mjs`).
- If the machine reboots before judging: rerun
  `deploy\start-sim-cloud-background.cmd` + `node deploy\cloud-check.mjs`.
- The captured transcript `docs/cloud-arc-transcript.md` stays in the repo as the
  permanent E2E record.
- Paste the uploaded video URL into `docs/devpost-draft.md` and the README.
