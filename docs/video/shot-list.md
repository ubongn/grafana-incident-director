# Shot List & Recording Guide — Demo Video

> Companion to [`../video-script.md`](../video-script.md) (the timed script — beats,
> narration, overlays). Canonical timings: run `run-20260827-163604-9fe96b`
> (FIRING 241.7 s · DETECT 4.56 · TRIANGULATE 13.67 · DIAGNOSE 15.52 · REMEDIATE
> 3.62 · GATE held · REPORT 8.41 · ≈46 s detect→report). If the recorded take
> differs, the TAKE's numbers win everywhere.
> Operator runbook (pre-flight, sim keep-alive, troubleshooting): [`../demo-day.md`](../demo-day.md).

---

## Setup (once, before recording)

| Item | Value |
|---|---|
| Recorder | OBS Studio — Scene "GID demo", 1920×1080, 30 fps, canvas = display |
| Encoder | x264, CRF 18–20 (or NVENC quality) — text must be crisp |
| Audio | USB mic, room quiet; record narration **separately** if easier (edit syncs it) |
| Browser | Chrome, light theme, zoom 110%, **incognito for all public-URL shots** |
| Terminal | Windows Terminal, light profile (`One Half Light`), Cascadia Mono 16 pt, ~100 cols, no wrap |
| Display | Windows light mode, hide taskbar (OBS fullscreen projector or crop), no notifications (Focus Assist on) |
| Theme | **Light everywhere.** Grafana dashboards already default light in this repo's provisioning |

**Pre-flight (30 min before, from demo-day.md):** sim alive
(`node deploy\cloud-check.mjs` → 30 series, fresh ts) · public dashboard renders
incognito · `python scripts\telemetry_selftest.py` → `OK: self-test series queryable`
· `python scripts\vertex_probe.py` → 200 · no scenarios active.

---

## Capture plan

Record **one long take** of the live arc plus pickup shots. The edit cuts it to the
script beats. The alert brew (~3.5 min) is covered by Beats 1–3 narration or timelapsed.

### Shot A — the live arc (main take, ~5 min, terminal fullscreen)

1. Start OBS recording **before** anything else.
2. Terminal at repo root. Type (on camera, slowly):
   `deploy\run-cloud-arc.cmd`
   (the exact fault inject it performs: `POST http://localhost:8790/scenarios/start`
   body `{"name":"cdn-edge-degraded"}` — see `sim/src/index.js:100`,
   `agent/incident_director/sim.py:50`.)
3. Let it run to completion — **do not touch mouse/keyboard** after the command.
   You'll see, in order: banner → DEMO_MODE gate note → inject → `waiting for alert`
   lines (~4 min brew: narrate Beats 1–5 over this, or timelapse in edit) →
   `FIRING after ~242s` → `[detect]` → `[triangulate]` → `[diagnose]` →
   `[remediate] proposal: … (XXs detect->proposal)` → `[gate] approved=False …` →
   `[report] …` → `[telemetry] agent run metrics -> ok` → DEMO SUMMARY JSON →
   incident report markdown.
4. **Keep the raw take.** The edit needs: FIRING line, all 6 phase lines, gate line,
   telemetry line, report markdown.

### Shot B — public dashboard healthy (for Beat 1, ~30 s)

- Incognito: `https://olivetiramisu3480.grafana.net/public-dashboards/10d81eda6d4d40058f07ad8b8b0f126a`
- Slow vertical scroll through the 15 panels, then park on "CDN edge latency p95"
  panel ~10 s. Cursor still.

### Shot C — alert firing state (Beat 2, ~20 s)

- Logged-in window: Alerting → Alert rules → `ott-edge-latency` in **Firing** state
  (red). This must be captured **while Shot A's brew is pending/firing** — the window
  is roughly t+60s…t+300s after inject. If missed: rerun the arc (or capture Pending
  state — also acceptable, it shows the brew honestly).

### Shot D — panels during incident (Beats 3–7 pickups, ~30 s)

- While FIRING (same window as C): dashboard `OTT Streaming Operations`,
  "CDN edge latency p95 by edge" (cdn-fra1 ~1,600–2,300 ms vs others ~100 ms) and
  "Playback error rate by region" (eu-west elevated). 5 s hold each, no scroll.

### Shot E — Loki evidence (Beat 8, ~20 s)

- Explore → Loki `loki-ott` → `{job="incident-director", service="cdn"} |= "timeout"`
  (or the dashboard Logs panel). Show 2–3 `upstream_fetch_timeout`/504 lines on
  cdn-fra1. During FIRING or within ~5 min after (Loki retains it).

### Shot F — annotation landing (Beat 11, ~20 s)

- Logged-in: `OTT Streaming Operations` dashboard after `[report]` printed.
  Annotation flag (tag `incident-director`) on a panel timeline; zoom browser 130%
  if the flag is small. Note: **public share strips annotations** (Grafana 13) —
  this shot MUST be the internal dashboard.

### Shot G — audit chain + eval matrix (Beat 11, ~25 s)

- Terminal: `incident-director audit` verify output (chain OK — e.g. 18 entries,
  run-20260827-163604-9fe96b hash-chained onto the morning run).
- Optional (ONLY if `evals/report.md` exists at recording time): its pass table,
  incl. the `traffic-spike` row (expected: refuse, got: refuse). Never ad-lib an
  eval score that isn't in the artifact.

### Shot H — agent observability (Beat 12, ~20 s)

- Logged-in: `https://olivetiramisu3480.grafana.net/d/agent-observability`
- Slow top-to-bottom pan: phase durations → detect→proposal / detect→report stats →
  tokens by direction → est. spend → gate decisions → run-event log tail.
- Best after **at least two arcs** (selftest + one real arc already land data; the
  recording-day arc adds the freshest point).

### Shot I — closing (Beat 13, ~15 s)

- Incognito public dashboard again (recovered/healthy), gentle scroll, end on
  "Active sessions" panel. Overlay closing-card.svg lands here.

---

## Edit checklist

- [ ] Total ≤ 3:00 (target 2:55). Only the first 3 min are judged.
- [ ] Brew timelapse keeps phase lines intact and ordered.
- [ ] Overlay numbers = numbers visible in the terminal take. Canonical (replace
      everywhere if the take differs): 1620.58 ms / 3.75% / 2.05% / 37.43 s
      detect→proposal / ≈46 s detect→report (video-script.md Beat 11).
- [ ] Gate line (Beat 10) holds ≥ 2 s with no overlay competing.
- [ ] Public URL visible twice (Beats 1, 13); repo URL once (closing card).
- [ ] Annotation shot = INTERNAL dashboard only; never claim it on the public link.
- [ ] No secrets on screen: no tokens, no `.env`, no terminal scrollback with creds
      (record terminal fresh; `cls` before Shot A).
- [ ] Light theme in every frame. No real logos (StreamFiction is fictional).
- [ ] Export: 1080p30, H.264 high, AAC 192k. Filename `grafana-incident-director-demo.mp4`.

## Voiceover booth notes (if narrating separately)

- Read ../video-script.md narration blocks verbatim; ~380 words total.
- The gate beat (10) is the hero: slow down 10% there.
- Pronounce: PromQL "prom-queue-el", LogQL "log-queue-el", PromQL/LogQL never spelled out.
- If a take runs long, trim Beats 1 and 3 first — never 6 or 9.
