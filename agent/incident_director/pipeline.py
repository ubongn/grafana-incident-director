"""Pipeline assembly: wire real components into an IncidentArc + helpers.

Also owns the demo wrapper (unattended, camera-friendly) and the
scenario->alert->arc convenience used by both CLI and evals.
"""

from __future__ import annotations

import asyncio
import time

from .actions.executor import RemediationExecutor
from .audit import AuditLog
from .config import Settings, apply_ai_env, load_settings
from .gate import ApprovalGate
from .runbook.arc import ArcResult, IncidentArc
from .sim import SimClient
from .watcher import AlertWatcher

# Which alert rule uids each fault scenario is expected to raise (eval + demo).
SCENARIO_ALERTS: dict[str, list[str]] = {
    "cdn-edge-degraded": ["ott-edge-latency", "ott-playback-errors"],
    "origin-5xx": ["ott-origin-5xx", "ott-playback-errors"],
    "drm-license-outage": ["ott-playback-errors"],
    "transcoder-backlog": ["ott-transcoder-lag", "ott-playback-errors"],
    "regional-isp-degradation": ["ott-rebuffer", "ott-playback-errors"],
    "traffic-spike": [],  # benign: no SLO rule may fire (NO-ACTION trap)
}

OPERATOR_PROMPTS: dict[str, str] = {
    "traffic-spike": (
        "Operator report: active sessions jumped ~60% in the last few minutes "
        "(live event starting). Assess whether this is an incident and what, "
        "if anything, should be done."
    ),
}


def build_arc(settings: Settings | None = None, verbose: bool = True) -> tuple[IncidentArc, Settings]:
    settings = settings or load_settings()
    problems = settings.validate_runtime()
    if problems:
        raise SystemExit("blocked:\n  - " + "\n  - ".join(problems))
    apply_ai_env(settings)
    audit = AuditLog(settings.audit_dir)
    mode = settings.approval_mode
    if settings.demo_mode and mode == "interactive":
        # DEMO_MODE=1 means an unattended camera run: never sit at a y/N
        # prompt and never execute without a human — force refuse_unattended.
        mode = "refuse_unattended"
        print("[demo] DEMO_MODE=1 -> approval gate forced to refuse_unattended (unattended never executes)")
    gate = ApprovalGate(mode=mode)
    executor = RemediationExecutor(settings)
    return IncidentArc(settings, audit, gate, executor, verbose=verbose), settings


async def run_scenario_once(
    scenario: str,
    params: dict | None = None,
    settings: Settings | None = None,
    demo: bool = False,
    auto_stop: bool = True,
    wait_timeout_s: float = 420.0,
) -> tuple[ArcResult, dict]:
    """Inject a fault, wait for its alert, run one arc. Returns (result, meta).

    meta records the harness-side timings (inject->firing seconds etc.).
    For traffic-spike (no alert) the arc is triggered by an operator report
    after confirming nothing is firing.
    """
    arc, settings = build_arc(settings, verbose=True)
    sim = SimClient(settings)
    watcher = AlertWatcher(settings)
    meta: dict = {"scenario": scenario}
    try:
        if await watcher.firing():
            raise SystemExit("refusing to inject: alerts already firing — stop active scenarios first")
        t_inject = time.monotonic()
        run = await sim.start(scenario, params)
        meta["scenario_id"] = run.id
        expected = SCENARIO_ALERTS.get(scenario)

        if expected:
            print(f"[harness] scenario '{scenario}' injected ({run.id}); waiting for alert {expected[0]} ...")
            rule_uid, waited = await watcher.wait_firing(expected, timeout_s=wait_timeout_s)
            meta["alert_rule_uid"] = rule_uid
            meta["inject_to_firing_s"] = round(time.monotonic() - t_inject, 1)
            print(f"[harness] {rule_uid} FIRING after {meta['inject_to_firing_s']}s")
            trigger_text = (
                f"Grafana SLO alert rule '{rule_uid}' is firing. "
                f"Scenario context: none given — investigate from the stack."
            )
            if demo:
                print("[demo] === ALERT->PROPOSAL 60s WINDOW OPEN ===")
            result = await arc.run("alert", trigger_text)
        else:
            # NO-ACTION trap: let it ramp, confirm nothing fires, trigger by operator report
            print(f"[harness] scenario '{scenario}' injected ({run.id}); benign — waiting out the ramp ...")
            await asyncio.sleep(150 if not demo else 100)
            firing = await watcher.firing()
            meta["alerts_firing_during_ramp"] = firing
            print(f"[harness] alerts firing during ramp: {firing or 'none'}")
            result = await arc.run("operator_report", OPERATOR_PROMPTS[scenario])

        meta["outcome"] = result.outcome
        from .telemetry import emit_run  # late import: telemetry must never break the arc

        emit_run(result, meta, settings, verbose=True)  # the telemetry line is demo material
        return result, meta
    finally:
        if auto_stop:
            try:
                await sim.stop_all()
            except Exception as e:  # pragma: no cover
                print(f"[harness] WARN: stop_all failed: {e}")
        await sim.close()
        await watcher.close()
