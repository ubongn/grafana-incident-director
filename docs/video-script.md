# Demo Video Script — "The Night Shift That Never Sleeps"

> **Runtime target: 2:55 (hard cap 3:00 — only the first 3 minutes are judged).**
> Everything on screen is the **real running product**: the live agent terminal, real
> MCP tool calls, Grafana Cloud dashboards. No slides, no mockups, no stock footage.
> Asset kit: overlays [`video/overlays/`](video/overlays/) · capture plan
> [`video/shot-list.md`](video/shot-list.md) · operator runbook [`demo-day.md`](demo-day.md).
>
> **Canonical run this script is timed against: `run-20260827-163604-9fe96b`**
> (2026-08-27 14:31–14:37 UTC, manager-witnessed, evidence in
> [`cloud-arc-transcript.md`](cloud-arc-transcript.md) + hash-chained
> `audit/audit-20260827.jsonl`). Narration lines are the spoken script (Ubong,
> warm, unhurried, ~135 wpm; ~380 words). "On screen" is exactly what the viewer
> sees. **Golden rule: numbers on screen do the arguing — narration only reads them.**

---

## The real commands (memorize these two lines)

**On camera — the whole arc is one command** (this is literally what was run live
on Aug 27):

```bat
deploy\run-cloud-arc.cmd
```

**Under the hood — the exact fault inject** the harness performs the moment the
runner starts (equivalently runnable by hand; the sim prints this form itself at
`sim/src/index.js:100`, the harness performs it at `agent/incident_director/sim.py:50`):

```bat
curl.exe -X POST http://localhost:8790/scenarios/start -H "Content-Type: application/json" -d "{\"name\":\"cdn-edge-degraded\"}"
```

Expected arc for that inject (run-20260827-163604-9fe96b, every phase first-attempt):

| Event | Wall time | Note |
|---|---|---|
| scenario `cdn-edge-degraded` injected (slot sc-004) | t0 | terminal prints `[harness] scenario 'cdn-edge-degraded' injected …` |
| rule `ott-edge-latency` Pending | t+60 s | visible in Alerting UI |
| rule `ott-edge-latency` **FIRING** | **t+241.7 s** | ~4 min brew (`for: 3m` + eval cadence) — timelapse in the edit |
| **DETECT** | **4.56 s** | 1 MCP tool call |
| **TRIANGULATE** | **13.67 s** | 16 MCP tool calls |
| **DIAGNOSE** | **15.52 s** | 3 MCP tool calls |
| **REMEDIATE** (proposal only) | **3.62 s** | 0 tool calls — by design |
| **GATE** | ~0 s | `approved=False decided_by=mode:refuse_unattended` |
| **REPORT** | **8.41 s** | 2 MCP tool calls |
| **DETECT→REPORT total** | **≈46 s** (45.78 s of phase time; 37.43 s detect→proposal) | |

---

## MOVEMENT I — HOOK

### BEAT 1 · Cold open: premiere night (0:00–0:12)

**On screen**
- Incognito browser (light theme): the public dashboard — 15 panels, "Active
  sessions: 2.1M", latency lines flat and healthy. Cursor idle, panels moving.
- Overlay L1 — title card (`overlays/title-card.svg`, 0:01–0:08):
  "Grafana Incident Director — an autonomous SRE runbook inside the Grafana stack".

**Narration**
> "Premiere night on StreamFiction — a simulated OTT platform with 2.1 million live
> sessions, streaming straight into Grafana Cloud. This dashboard is public, no
> login — the link is in the repo, and it is live right now."

### BEAT 2 · Break it (0:12–0:26)

**On screen**
- Terminal (light profile): type the one command, slowly, on camera:
  `deploy\run-cloud-arc.cmd` then Enter. Terminal prints:
  `[harness] scenario 'cdn-edge-degraded' injected (sc-004); waiting for alert ott-edge-latency ...`
- Overlay L2 — lower third (0:14–0:24): `inject: POST :8790/scenarios/start
  {"name":"cdn-edge-degraded"} — one Frankfurt edge, cdn-fra1, starts timing out`.

**Narration**
> "Now let's break it. One command injects a fault: the CDN edge in Frankfurt starts
> timing out. The alert needs about four minutes to brew, so we'll let it — and the
> agent watches the stack while we watch the dashboards."

---

## MOVEMENT II — LIVE ARC ON THE DASHBOARD

### BEAT 3 · The brew, honestly (0:26–0:40)

**On screen**
- Timelapse of the terminal's `waiting for alert...` lines (compressed to ~4 s),
  then cut to the **public dashboard** (incognito): "CDN edge latency p95 by edge" —
  the cdn-fra1 line ramps ~100 ms → ~2,200 ms; "Playback error rate by region" —
  eu-west ticks up. Every other line stays flat.
- Overlay L3 (0:30–0:38): "real remote-write telemetry — cdn-fra1 p95 ~2,260 ms
  @14:34Z vs ~100 ms baseline (public dashboard's own window)".

**Narration**
> "This is the real telemetry moving — hosted Prometheus, remote-written from the
> simulator. One edge degrades; every other region stays flat. That asymmetry is
> what the agent is about to exploit."

### BEAT 4 · FIRING (0:40–0:52)

**On screen**
- Logged-in window: Alerting → Alert rules → `ott-edge-latency` flips Pending →
  **Firing** (red). Hold the red state one full second.
- Cut back to terminal: `[harness] ott-edge-latency FIRING after ~242s` then the
  arc banner `=== incident arc run-… (trigger: alert) ===`.
- Overlay L4 (0:42–0:50): "SLO alert FIRING — p95 > 800 ms for 3 min · this is the
  agent's pager".

**Narration**
> "At 2 a.m. this is the moment a human's phone buzzes. For us, it's the agent's
> cue to clock in."

---

## MOVEMENT III — THE AGENT, MCP-TAGGED (every step names its Grafana MCP tool)

### BEAT 5 · Meet the Incident Director (0:52–1:04)

**On screen**
- 2-second cut-in of [`architecture.svg`](architecture.svg) (pan left→right):
  simulator → Prometheus/Loki → **Grafana MCP server** → phase agents →
  **policy gate** → **action ledger**.
- Overlay L5 (0:53–1:02): "Google ADK + Gemini 2.5 Flash on Vertex AI · the agent's
  ONLY hands: the Grafana MCP server (mcp-grafana)".

**Narration**
> "Incident Director is a five-phase runbook agent built on Google ADK, with Gemini
> on Vertex AI as the brain — and one compliance-critical rule: its only hands are
> the Grafana MCP server. Every query, every log scan, every annotation goes
> through MCP. Watch the tool names as each phase runs."

### BEAT 6 · DETECT — 4.56 s (1:04–1:16)

**On screen**
- Terminal: `[detect]` block rolls (real take). MCP tag flashes on screen.
- Overlay L6 (1:06–1:14): "DETECT — 4.56 s · MCP: `alerting_manage_rules` · 1 firing
  rule isolated from 5 SLO rules".

**Narration**
> "Detect: four point five six seconds. One MCP call reads the live alert state —
  one rule firing out of five SLOs. Edge latency, and nothing else."

### BEAT 7 · TRIANGULATE — 13.67 s (1:16–1:42)

**On screen**
- Terminal: `[triangulate]` verdict prints — zoom 120% when the numbers land.
- Picture-in-picture (bottom-right): public dashboard "CDN edge latency p95 by
  edge" — cdn-fra1 ~1,620 ms vs ~100 ms everywhere else.
- Overlay L7 (1:18–1:38): "TRIANGULATE — 13.67 s · MCP: `get_dashboard_panel_queries`
  ×8 + `query_prometheus` ×8 — the agent runs the dashboard's own PromQL, live:
  cdn-fra1 1620.58 ms · 5xx 3.75% · eu-west playback errors 2.05% · every other
  region normal".

**Narration** (read the terminal's own numbers)
> "Triangulate pulls the dashboard's own PromQL through MCP and runs the
  comparisons live: cdn-fra1 at sixteen hundred twenty milliseconds p95, three
  point seven five percent 5xx, playback errors at two percent in eu-west — every
  other region normal. Scope: one edge, one region."

### BEAT 8 · DIAGNOSE — 15.52 s (1:42–2:00)

**On screen**
- Terminal: `[diagnose]` prints the root cause, `conf=0.9`.
- Quick cut: Grafana Explore on Loki — 2–3 `upstream_fetch_timeout → 504` lines at
  cdn-fra1 highlighted.
- Overlay L8 (1:44–1:58): "DIAGNOSE — 15.52 s · MCP: `find_error_pattern_logs` ×2 +
  `query_loki_logs` — root cause grounded in logs, not vibes".

**Narration**
> "Diagnose refuses to guess. Three MCP calls into Loki find the smoking gun —
  upstream fetch timeouts cascading into 504s at that exact edge. Root cause,
  confidence zero point nine, with the log lines to back it."

### BEAT 9 · REMEDIATE — propose only (2:00–2:12)

**On screen**
- Terminal: the full proposal block — class `drain_cdn_edge`, params
  `{"edge": "cdn-fra1"}`, effect / risk / rollback / rationale. 3.62 s timer.
- Overlay L9 (2:02–2:10): "REMEDIATE — 3.62 s · zero tool calls by design: it
  drafts the fix, it never executes".

**Narration**
> "The fix is surgical — drain one edge, with an explicit effect, risk and rollback.
> And note: zero tool calls. Proposing is not executing."

---

## MOVEMENT IV — THE GATE (hero moment — slow down here)

### BEAT 10 · GATE HELD (2:12–2:26)

**On screen**
- Terminal: `[gate] approved=False decided_by=mode:refuse_unattended` —
  **hold 2 full seconds, no overlay competing**.
- Then overlay L10 — gate band (`overlays/gate-band.svg`, 2:15–2:25): "THE GATE —
  unattended runs never touch production. An interactive human approves, or
  nothing happens."

**Narration** (10% slower)
> "And then it stops. The framework-enforced gate refuses: unattended mode means a
  human approves, or nothing executes. The agent diagnosed the whole incident in
  under forty seconds — and still didn't touch production. Fast, and leashed."

---

## MOVEMENT V — 46 SECONDS, END TO END (the evidence)

### BEAT 11 · REPORT + the tally (2:26–2:44)

**On screen**
- Terminal: `[report]` posts the annotation and runs a verification query — honest
  post-state: "latency still ~2,025 ms — remediation denied".
- Cut: **internal** dashboard (logged in) — annotation flag (tag `incident-director`)
  lands on the panel timeline at 14:36:45Z.
- Overlay L11 (2:28–2:42): the tally — "4.56 + 13.67 + 15.52 + 3.62 + 8.41 =
  **DETECT→REPORT ≈46 s** · every phase first-attempt · 18-entry hash-chained audit,
  chain verified".

**Narration**
> "The report writes the incident back into Grafana — an annotation on the
  dashboard, a verification query, and an honest post-state: latency is still high,
  because remediation was denied. Total: four point five six, thirteen point six
> seven, fifteen point five two, three point six two, eight point four one — about
> forty-six seconds, alert to report, first attempt, every step in a hash-chained
> audit log."

**Honesty guard (do NOT skip):** the annotation is visible on the **internal**
dashboard only — Grafana 13 public shares strip the annotations layer. On the
public dashboard, the arc shows through its data footprint (the cdn-fra1 spike).
Never say "and there's the annotation on the public link."

### BEAT 12 · The observer, observed (2:44–2:52) *(optional — first cut to trim)*

**On screen**
- `/d/agent-observability` (logged-in): phase durations, detect→proposal 37.43 s,
  tokens by direction, est. spend, gate decision = denied. One slow pan.
- Overlay L12 — `overlays/agent-obs-card.svg`: "the agent publishes its own phase
  timings, tool calls, tokens and spend — to the stack it manages".

**Narration**
> "And because this is Grafana, the agent watches itself: phase timings, tool
> calls, tokens and cost — published to the very stack it manages."

---

## MOVEMENT VI — CLOSE

### BEAT 13 · Card + link (2:52–2:55)

**On screen**
- Public dashboard, recovered and healthy. Overlay L13 — closing card
  (`overlays/closing-card.svg`): title + public URL + repo URL.

**Narration**
> "This exact dashboard is live right now — no login. Go click it."

---

## Timing budget

| Beat | Window | s | Cumulative |
|---|---|---|---|
| 1 Cold open | 0:00–0:12 | 12 | 0:12 |
| 2 Inject | 0:12–0:26 | 14 | 0:26 |
| 3 Brew timelapse | 0:26–0:40 | 14 | 0:40 |
| 4 FIRING | 0:40–0:52 | 12 | 0:52 |
| 5 Meet the agent | 0:52–1:04 | 12 | 1:04 |
| 6 DETECT | 1:04–1:16 | 12 | 1:16 |
| 7 TRIANGULATE | 1:16–1:42 | 26 | 1:42 |
| 8 DIAGNOSE | 1:42–2:00 | 18 | 2:00 |
| 9 REMEDIATE | 2:00–2:12 | 12 | 2:12 |
| 10 GATE HELD ★ | 2:12–2:26 | 14 | 2:26 |
| 11 REPORT + tally | 2:26–2:44 | 18 | 2:44 |
| 12 Agent observability | 2:44–2:52 | 8 | 2:52 |
| 13 Close | 2:52–2:55 | 3 | **2:55** |

## Cut rules

1. **Never cut:** the inject line, the FIRING line, any MCP tool tag, the gate
   line (Beat 10), or the 46-second tally (Beat 11). These six moments ARE the video.
2. The ~4-minute brew is always a timelapse; all phase lines stay intact and ordered.
3. If a take runs long, trim Beats 3 and 12 first — never 10 or 11.
4. **Numbers discipline:** overlays and narration print run-20260827-163604-9fe96b
   values; if the final recorded take differs, replace EVERYWHERE (terminal numbers
   on screen are the source of truth — narration reads what's visible, never fights it).
5. Only claims provable on screen: MCP tool names, phase timings, gate refusal,
   annotation on the internal dashboard, audit chain OK. Eval-matrix scores only if
   `evals/report.md` exists at recording time (see `evals/harness.py` — the
   no-action trap is graded there; don't ad-lib a score).
6. Light theme everywhere; incognito for every public-URL shot; no tokens or
   scrollback with credentials in frame (fresh terminal, `cls` first).
