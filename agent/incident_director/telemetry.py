"""Agent self-observability: publish per-run telemetry to Grafana Cloud.

Every completed incident arc emits its OWN telemetry to the same stack the
agent operates on — phase timings, tool usage, model tokens and estimated
cost land in hosted Prometheus/Loki and drive the "Agent Observability"
dashboard (deploy/grafana/dashboards/agent-observability.json). Observing
the observer: the runbook's evidence trail plus a cost/latency budget for
the agent itself.

Transport notes (why this file looks the way it does):
- Prometheus remote-write goes through sim/src/telemetry-push.mjs (Node),
  which uses the same `prometheus-remote-write` package as the simulator.
  A hand-rolled protobuf probe once returned HTTP 200 but the series never
  became queryable — the packaged client is the known-good transport.
- Loki push is a plain JSON POST; httpx from here is fine.
- Emission is best-effort and env-gated (AGENT_TELEMETRY=0 disables):
  telemetry must never fail an incident arc.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .config import Settings
    from .runbook.arc import ArcResult

REPO_ROOT = Path(__file__).resolve().parents[2]
PUSHER = REPO_ROOT / "sim" / "src" / "telemetry-push.mjs"

# Gemini 2.5 Flash list pricing (Vertex, USD per 1M tokens). Thoughts are
# billed as output tokens. Label travels with the metric so the dashboard
# never presents an estimate as a bill.
PRICE_PER_MTOK = {"gemini-2.5-flash": (0.30, 2.50)}
PRICING_LABEL = "gemini-2.5-flash_vertex_list_usd"

# Directions that count as billable output for the cost estimate.
_OUTPUT_DIRS = ("candidates", "thoughts")


def estimate_cost_usd(usage: dict, model: str) -> float:
    """Estimated spend for one phase's token usage, at published list price."""
    per_m = PRICE_PER_MTOK.get(model)
    if per_m is None or not usage:
        return 0.0
    price_in, price_out = per_m
    tok_in = usage.get("prompt", 0) or 0
    tok_out = sum(usage.get(d, 0) or 0 for d in _OUTPUT_DIRS)
    return round(tok_in / 1e6 * price_in + tok_out / 1e6 * price_out, 6)


def _sample(name: str, labels: dict, value) -> dict | None:
    if value is None:
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    clean = {
        "__name__": name,
        "job": "incident-director",
        "source": "agent",
        **{str(k): str(v_) for k, v_ in labels.items() if v_ not in (None, "")},
    }
    return {"labels": clean, "samples": [{"value": v}]}


def run_samples(result: "ArcResult", meta: dict, model: str) -> list[dict]:
    """Build the remote-write payload for one completed arc."""
    out: list[dict] = []

    def add(name: str, labels: dict, value) -> None:
        s = _sample(name, labels, value)
        if s is not None:
            out.append(s)

    for rec in result.phases:
        add("incident_director_phase_seconds", {"phase": rec.phase, "ok": str(rec.ok).lower()}, rec.seconds)
        add("incident_director_phase_attempts", {"phase": rec.phase}, rec.attempts)
        for tool in rec.tool_calls:
            add("incident_director_phase_tool_calls", {"phase": rec.phase, "tool": tool}, 1)
        for direction, n in (rec.usage or {}).items():
            add("incident_director_model_tokens", {"phase": rec.phase, "direction": direction}, n)
        cost = estimate_cost_usd(rec.usage or {}, model)
        if cost:
            add(
                "incident_director_model_cost_usd",
                {"phase": rec.phase, "model": model, "pricing": PRICING_LABEL},
                cost,
            )

    add("incident_director_detect_to_proposal_seconds", {}, result.detect_to_proposal_s)
    if result.t_end and result.t_start:
        add("incident_director_detect_to_report_seconds", {}, round(result.t_end - result.t_start, 2))
    scenario = str(meta.get("scenario", result.trigger_type))
    add("incident_director_run_outcome", {"outcome": result.outcome, "scenario": scenario}, 1)
    gate = result.gate
    decision = f"{gate.decided_by}:{'approved' if gate.approved else 'refused'}" if gate else "n/a"
    add("incident_director_gate_decision", {"decision": decision}, 1)
    if meta.get("inject_to_firing_s") is not None:
        add(
            "incident_director_alert_brew_seconds",
            {"rule": str(meta.get("alert_rule_uid", "unknown"))},
            meta["inject_to_firing_s"],
        )
    return [s for s in out if s]


def loki_payload(result: "ArcResult", meta: dict, model: str) -> dict:
    """One structured run-event line for the dashboard's run table."""
    total_usage: dict[str, int] = {}
    total_cost = 0.0
    for rec in result.phases:
        for d, n in (rec.usage or {}).items():
            total_usage[d] = total_usage.get(d, 0) + n
        total_cost += estimate_cost_usd(rec.usage or {}, model)

    line = json.dumps(
        {
            "run_id": result.run_id,
            "scenario": meta.get("scenario", ""),
            "trigger": result.trigger_type,
            "outcome": result.outcome,
            "executed": bool(result.executed),
            "detect_to_proposal_s": result.detect_to_proposal_s,
            "detect_to_report_s": round(result.t_end - result.t_start, 2) if result.t_end and result.t_start else -1.0,
            "brew_s": meta.get("inject_to_firing_s"),
            "phases": {r.phase: r.seconds for r in result.phases},
            "gate": (f"{result.gate.decided_by}:{'approved' if result.gate.approved else 'refused'}" if result.gate else ""),
            "model": model,
            "tokens": total_usage,
            "est_cost_usd": round(total_cost, 6),
            "pricing": PRICING_LABEL if total_cost else "",
        },
        separators=(",", ":"),
    )
    return {
        "streams": [
            {
                "stream": {
                    "job": "incident-director",
                    "source": "agent",
                    "model": model,
                    "outcome": result.outcome or "unknown",
                },
                "values": [[str(int(time.time() * 1e9)), line]],
            }
        ]
    }


def _enabled() -> bool:
    return os.environ.get("AGENT_TELEMETRY", "1").strip().lower() not in ("0", "false", "no", "off")


def _push_prom(samples: list[dict]) -> tuple[bool, str]:
    if not samples:
        return True, "no samples"
    if not os.environ.get("PROMETHEUS_REMOTE_WRITE_URL"):
        return False, "PROMETHEUS_REMOTE_WRITE_URL not set (local stack: expected, skipped)"
    if not PUSHER.is_file():
        return False, f"pusher missing: {PUSHER}"
    try:
        proc = subprocess.run(
            ["node", str(PUSHER)],
            input=json.dumps({"samples": samples}),
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(REPO_ROOT),
        )
    except (OSError, subprocess.SubprocessError) as e:
        return False, f"pusher error: {e}"
    if proc.returncode != 0:
        return False, f"pusher exit {proc.returncode}: {(proc.stderr or '').strip()[:200]}"
    return True, (proc.stdout or "").strip()


def _push_loki(payload: dict) -> tuple[bool, str]:
    import httpx

    url = os.environ.get("LOKI_PUSH_URL", "").strip()
    if not url:
        return False, "LOKI_PUSH_URL not set (local stack: expected, skipped)"
    user = os.environ.get("LOKI_USERNAME", "").strip()
    key = os.environ.get("GRAFANA_CLOUD_API_KEY", "").strip()
    headers = {"Content-Type": "application/json"}
    auth = (user, key) if user and key else None
    try:
        resp = httpx.post(url, content=json.dumps(payload), headers=headers, auth=auth, timeout=15)
    except httpx.HTTPError as e:
        return False, f"loki error: {e}"
    if resp.status_code >= 300:
        return False, f"loki status {resp.status_code}: {resp.text[:200]}"
    return True, f"loki {resp.status_code}"


def emit_run(result: "ArcResult", meta: dict, settings: "Settings", verbose: bool = True) -> None:
    """Best-effort telemetry emission for one completed arc. Never raises."""
    if not _enabled():
        return
    try:
        model = settings.gemini_model
        samples = run_samples(result, meta, model)
        ok_prom, msg_prom = _push_prom(samples)
        ok_loki, msg_loki = _push_loki(loki_payload(result, meta, model))
        if verbose:
            status = "ok" if ok_prom else "skipped"
            print(
                f"[telemetry] agent run metrics -> {status} "
                f"({len(samples)} samples, {msg_prom}; {msg_loki})",
                flush=True,
            )
    except Exception as e:  # pragma: no cover - telemetry must never break the arc
        if verbose:
            print(f"[telemetry] WARN: emission failed: {e}", file=sys.stderr, flush=True)
