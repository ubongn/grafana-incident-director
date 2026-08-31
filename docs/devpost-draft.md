# Devpost Submission Draft — Grafana Incident Director (Agentic Cinema, Grafana track)

> **Source of truth for every portal field.** Final paste happens on the hackathon
> portal; edit here first. Companion artifacts: timed video script
> [`video-script.md`](video-script.md) · demo runbook [`demo-day.md`](demo-day.md) ·
> E2E evidence [`cloud-arc-transcript.md`](cloud-arc-transcript.md) ·
> architecture [`architecture.svg`](architecture.svg).
>
> **Numbers rule:** every figure below is from the manager-witnessed canonical run
> `run-20260827-163604-9fe96b` (audit-chained in `audit/audit-20260827.jsonl`,
> entries 10–18). If a fresher run is captured for the video, refresh figures here.

---

## Title

**Grafana Incident Director — an autonomous SRE runbook living inside Grafana**

*(strict ≤60-char fallback: "Grafana Incident Director — autonomous incident runbook")*

## Elevator pitch (99 words)

> When an SLO burns at 2 a.m., a human opens fifteen tabs and starts guessing.
> Grafana Incident Director is an autonomous agent that runs the whole
> first-response loop inside Grafana: detect the firing rule, triangulate the
> blast radius with live PromQL, ground the root cause in Loki logs, propose a
> minimal remediation — then stop at a human-approval gate and write the report
> back as a dashboard annotation. Built on Google ADK with Gemini on Vertex AI,
> its only hands are the Grafana MCP server. Every claim is cited, every run is
> hash-chained, and the agent publishes its own cost and latency to the stack
> it manages.

## Team

Ubong N. (solo) — repo `ubongn/grafana-incident-director`.

## URLs

| Field | Value |
|---|---|
| Repository (public, MIT) | <https://github.com/ubongn/grafana-incident-director> |
| **Hosted demo — public dashboard, NO LOGIN** | <https://olivetiramisu3480.grafana.net/public-dashboards/10d81eda6d4d40058f07ad8b8b0f126a> |
| Full ops dashboard (login) | <https://olivetiramisu3480.grafana.net/d/ott-streaming-ops> |
| Agent Observability dashboard (login) | <https://olivetiramisu3480.grafana.net/d/agent-observability> |
| Demo video (≤3:00) | `https://youtu.be/…` ← **placeholder — paste after upload (record ~Sep 5–7)** |
| E2E evidence transcript | [`docs/cloud-arc-transcript.md`](https://github.com/ubongn/grafana-incident-director/blob/main/docs/cloud-arc-transcript.md) |
| License | MIT — [`LICENSE`](https://github.com/ubongn/grafana-incident-director/blob/main/LICENSE), badge in README |

---

## Description (mirrors the judging rubric)

### Technological Implementation

**A deterministic five-phase runbook, not a chat loop.** Google ADK (Python)
orchestrates Detect → Triangulate → Diagnose → Remediate → Report with one
`LlmAgent` per phase — Gemini **2.5 Flash on Vertex AI** (`us-central1`,
service-account ADC, temperature 0, structured JSON outputs; provider seam
`AI_PROVIDER` in `agent/incident_director/config.py`). The simulated OTT platform
(StreamFiction: 2.1M sessions, 6 regions, 5 fault classes + one benign spike)
remote-writes into **Grafana Cloud** hosted Prometheus/Loki, so the agent runs
against the real hosted stack end to end.

**Grafana MCP server is the agent's only pair of hands — by construction.** Every
stack interaction at runtime is an MCP tool call; there is no direct datasource
HTTP in the agent:

| Where (file:line) | What it proves |
|---|---|
| `agent/incident_director/grafana/mcp.py:26–51` | phase-narrowed MCP tool allowlists (DETECT `alerting_manage_rules`; TRIANGULATE `get_dashboard_panel_queries`+`query_prometheus`; DIAGNOSE `query_loki_logs`+`find_error_pattern_logs`; REPORT `create_annotation`+`query_prometheus`) |
| `agent/incident_director/grafana/mcp.py:86` | one `MCPToolset` built per phase agent — its own `mcp-grafana` stdio process, service-account auth |
| `agent/incident_director/config.py:66–76` | mcp-grafana launch resolution (installed binary → `uvx mcp-grafana@latest`) |
| `agent/incident_director/runbook/agents.py:4` | every phase agent is an ADK `LlmAgent` + MCPToolset bound to mcp-grafana with a phase-narrow tool filter |
| `agent/incident_director/runbook/prompts.py:81,108,136–139,188–190` | each phase prompt instructs the exact MCP tools (incl. annotation write-back + PromQL verification) |

**Runtime proof (run-20260827-163604-9fe96b, hash-chained audit):** the audit
entries record the exact MCP tool calls per phase — `detect: [alerting_manage_rules]`;
`triangulate: [get_dashboard_panel_queries ×8, query_prometheus ×8]`;
`diagnose: [find_error_pattern_logs ×2, query_loki_logs]`; `remediate: []`
(proposes, never executes); `report: [create_annotation, query_prometheus]`
(annotation id=2 posted 14:36:45Z). FIRING 241.7 s after inject; DETECT 4.56 s ·
TRIANGULATE 13.67 s · DIAGNOSE 15.52 s · REMEDIATE 3.62 s · GATE held ·
REPORT 8.41 s → **≈46 s detect→report (37.43 s detect→proposal), every phase
first-attempt**.

### Design

The product IS the loop, and the video shows it live: firing SLO alert → scoped
triangulation (cdn-fra1 at 1620.58 ms p95, 5xx 3.75%, eu-west playback errors
2.05% — every other region normal) → log-grounded diagnosis (upstream fetch
timeouts → 504s, confidence 0.9) → surgical proposal (`drain_cdn_edge`, with
explicit effect/risk/rollback) → **gate refusal** → annotation written back to
the dashboard with an honest verification ("latency ~2025 ms persists —
remediation denied"). The approval gate is the hero moment, not a footnote.
Operators keep their existing dashboards; the agent writes into them instead of
replacing them. Demo honesty is engineered: Grafana 13 public shares strip the
annotations layer (verified live), so the public link shows the arc via its data
footprint and the annotation is demonstrated on the internal dashboard.

### Potential Impact

Every Grafana-using SRE team already has the telemetry; what they lack at 3 a.m.
is a *directed* first response. This pattern — deterministic runbook + MCP-only
hands + human gate + hash-chained audit — generalizes to any domain Grafana
already observes (payments, infrastructure, manufacturing lines). The NO-ACTION
trap proves the safety story: a benign traffic spike is assessed and correctly
*not* remediated — the eval harness (`evals/harness.py`) grades refuse-to-act as
the only passing answer for that scenario. Post-incident, the evidence chain
(queries, log lines, decisions) is the postmortem skeleton, already in the stack.

### Quality of Idea

Three bets, all demonstrable: (1) **agents as runbook executors, not chatbots** —
the value is the deterministic loop; the LLM is one component per phase;
(2) **observe the observer** — the agent publishes its own phase timings, tool
calls, token counts and list-price cost estimate to the same Grafana it manages
(the Agent Observability dashboard), turning AI spend into a first-class Grafana
problem; (3) **leashed autonomy** — speed without surrendering control: the
policy gate, the hash-chained action ledger, and the graded eval matrix make it
auditable enough to actually be allowed on-call.

---

## Monitoring & evaluation (M&E) workflow — real, not slideware

1. **Live monitoring:** StreamFiction sim → remote-write → hosted Prometheus/Loki;
   5 SLO alert rules (p95 latency, rebuffer, origin 5xx, edge latency, transcoder
   lag) provisioned by `deploy/provision_cloud.py`; the arc is *triggered* by a
   real firing alert, not a script flag.
2. **Run ledger:** every phase, proposal, gate decision and report lands in a
   SHA-256 hash-chained audit file (`audit/audit-20260827.jsonl` — 18 entries
   across both Aug-27 runs, `incident-director audit verify` = chain OK).
   The transcript is the committed, human-readable view of that chain.
3. **Graded evaluation:** `evals/harness.py` re-runs the full pipeline per
   scenario and grades against the simulator as ground truth — the sim only
   accepts the action+params that neutralize the injected fault, so
   `outcome=executed` proves class- AND parameter-correctness; the traffic-spike
   trap passes only on refusal. Report artifact: `evals/report.md`
   (**final matrix numbers pasted here after the pre-submit run**).
4. **Self-observability:** the agent emits its own run telemetry (phase seconds,
   tool-call markers, tokens by direction, list-price cost, gate decision) to the
   same hosted stack — visible on `/d/agent-observability`.

## Built-with / attribution (portal tags)

- **Google Cloud (AI is Google-only by design):** Gemini 2.5 Flash on **Vertex AI**,
  Google ADK agent framework, service-account ADC.
- **Grafana:** Grafana Cloud (hosted Prometheus, Loki, dashboards, alerting,
  public-dashboard sharing), **Grafana MCP server (`mcp-grafana`)** as the agent's
  runtime interface, annotations API for write-back.
- **Everything else:** Python 3.12 / uv, Node 22 (telemetry simulator), pytest
  (82/82 green). Simulated data only — StreamFiction is fictional; no real user
  data. **MIT licensed**, source public.

## Honesty checklist (pre-submit)

- [ ] Video recorded per `docs/video-script.md`, ≤3:00, uploaded, URL pasted above
- [ ] Video narration claims ONLY what's on screen (annotation = internal dashboard; public link = data footprint)
- [ ] Eval matrix run → `evals/report.md` committed → numbers pasted into §M&E
- [ ] Hosted URL live **and sim kept alive** through judging (`deploy\start-sim-cloud-background.cmd` + daily `node deploy\cloud-check.mjs`)
- [ ] Repo public, README badges accurate, no secrets in history (`git log -p` scan)
- [ ] This file's numbers match the final video take
- [ ] Submit ≥24 h before Sep 9 22:00 WAT close (target: Sep 6)
