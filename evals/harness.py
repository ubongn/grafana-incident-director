"""Graded eval matrix for the Incident Director (M2 acceptance harness).

Runs the full pipeline N times over the sim's six fault scenarios and grades
every run. No LLM output is trusted on faith — grading is against the sim as
ground truth: the sim's /remediate endpoint only accepts the action+params
that actually neutralize the injected fault, so `outcome == executed` means
the proposal was class-correct AND parameter-correct.

Grading rules:
- fault scenarios: proposal.action == "execute", remediation_class == the
  expected class for that fault, gate passed, executor accepted by the sim
  (outcome "executed"). Anything else is a FAIL with the reason recorded.
- traffic-spike (the NO-ACTION trap): the agent MUST refuse —
  action == "refuse", remediation_class == "none", outcome "refused" — and no
  SLO alert may have fired during the ramp (a false alarm fails the run).

Gate mode is forced to auto_approve (with the ALLOW_AUTO_APPROVE=1 double
opt-in) so the closed loop executes and the executor's verdict is gradable.
The double opt-in stays inside this harness; nothing else flips it.

Outputs (under evals/ by default):
- results.json — raw per-run records (meta + grade + proposal)
- report.md   — the committed artifact: pass table + latency medians

Exit code 0 iff every run of every scenario passed (N/N).

Usage:
    python -m incident_director.cli eval --runs 2
    python evals/harness.py --runs 2 --scenarios cdn-edge-degraded,traffic-spike
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

EVALS_DIR = Path(__file__).resolve().parent
REPO_ROOT = EVALS_DIR.parent
sys.path.insert(0, str(REPO_ROOT / "agent"))

from incident_director.config import load_settings  # noqa: E402
from incident_director.pipeline import SCENARIO_ALERTS, run_scenario_once  # noqa: E402
from incident_director.sim import SimClient  # noqa: E402
from incident_director.watcher import AlertWatcher  # noqa: E402

# The one correct remediation class per fault scenario (mirrors sim/src/scenarios.js docs).
EXPECTED_CLASS: dict[str, str | None] = {
    "cdn-edge-degraded": "drain_cdn_edge",
    "origin-5xx": "failover_origin",
    "drm-license-outage": "switch_license_endpoint",
    "transcoder-backlog": "throttle_ingest",
    "regional-isp-degradation": "tighten_abr_floor",
    "traffic-spike": None,  # benign: the only correct answer is to refuse
}

TRAP = "traffic-spike"
SETTLE_TIMEOUT_S = 240.0


@dataclass
class Grade:
    passed: bool
    reason: str


def grade_run(scenario: str, result: Any, meta: dict) -> Grade:
    """Grade one arc result against the scenario's expected outcome.

    Pure function (offline-testable): no I/O, no clock.
    """
    expected = EXPECTED_CLASS.get(scenario, "__unknown_scenario__")
    if expected == "__unknown_scenario__":
        return Grade(False, f"unknown scenario '{scenario}'")

    prop = result.proposal
    if prop is None:
        return Grade(False, f"no proposal (outcome={result.outcome}, error={result.error[:120]})")

    if expected is None:  # NO-ACTION trap
        if prop.action != "refuse" or prop.remediation_class != "none":
            return Grade(
                False,
                f"TRAP EXECUTED: proposed {prop.action}/{prop.remediation_class} "
                f"params={prop.params} — benign load must be refused",
            )
        if result.outcome != "refused":
            return Grade(False, f"refusal shape ok but outcome={result.outcome} (want 'refused')")
        fired = meta.get("alerts_firing_during_ramp") or []
        if fired:
            return Grade(False, f"false alarm during ramp: {fired}")
        return Grade(True, "refused benign spike; class=none; no SLO alert fired")

    if prop.action != "execute":
        return Grade(
            False,
            f"proposed {prop.action}/{prop.remediation_class} — wanted execute/{expected}",
        )
    if prop.remediation_class != expected:
        return Grade(False, f"wrong class: {prop.remediation_class} (want {expected})")
    if result.outcome != "executed":
        detail = result.execution_detail or result.error or "no detail"
        return Grade(False, f"not executed: outcome={result.outcome} :: {detail[:160]}")
    return Grade(True, f"executed {expected} :: {result.execution_detail[:160]}")


def _median_detect_to_proposal(rows: list[dict]) -> float | None:
    vals = [r["detect_to_proposal_s"] for r in rows if r["detect_to_proposal_s"] and r["detect_to_proposal_s"] > 0]
    return round(statistics.median(vals), 2) if vals else None


def write_report(rows: list[dict], runs: int, out_path: Path) -> None:
    """Render evals/report.md from graded rows."""
    by_scenario: dict[str, list[dict]] = {}
    for r in rows:
        by_scenario.setdefault(r["scenario"], []).append(r)

    lines: list[str] = []
    lines.append("# Eval Report — Incident Director (M2 acceptance)")
    lines.append("")
    lines.append(f"- **Date (UTC):** {time.strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"- **Matrix:** {runs} run(s) x {len(by_scenario)} scenario(s) = {len(rows)} graded runs")
    lines.append("- **Gate mode during eval:** `auto_approve` (double opt-in, harness-local) — "
                 "grades the closed loop: proposal -> gate -> executor -> sim acceptance. "
                 "The sim rejects any action/params that do not actually neutralize the fault, "
                 "so `executed` means class- and parameter-correct.")
    lines.append("- **Trap:** `traffic-spike` is benign load. The only passing outcome is a "
                 "REFUSAL (`action=refuse`, `class=none`) with no SLO alert fired during the ramp.")
    lines.append("")

    total = len(rows)
    passed = sum(1 for r in rows if r["passed"])
    med_all = _median_detect_to_proposal([r for r in rows if r["scenario"] != TRAP])
    lines.append(f"## Verdict: **{passed}/{total} passed**"
                 + (f" — median detect→proposal **{med_all}s** (fault scenarios)" if med_all is not None else ""))
    lines.append("")

    lines.append("## Per-scenario pass table")
    lines.append("")
    lines.append("| Scenario | Pass | Median detect→proposal (s) | Notes |")
    lines.append("|---|---|---|---|")
    for sc in SCENARIO_ALERTS:
        rs = by_scenario.get(sc, [])
        if not rs:
            lines.append(f"| {sc} | — | — | not run |")
            continue
        ok = sum(1 for r in rs if r["passed"])
        med = _median_detect_to_proposal(rs) if sc != TRAP else None
        med_s = f"{med}s" if med is not None else "n/a (refusal path)"
        first_fail = next((r for r in rs if not r["passed"]), None)
        note = "all runs passed" if ok == len(rs) else (first_fail["reason"] if first_fail else "")
        marker = " (NO-ACTION trap)" if sc == TRAP else ""
        lines.append(f"| {sc}{marker} | **{ok}/{len(rs)}** | {med_s} | {note} |")
    lines.append("")

    lines.append("## Per-run detail")
    lines.append("")
    lines.append("| # | Scenario | Pass | Outcome | Class | detect→proposal (s) | inject→firing (s) | Reason |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for i, r in enumerate(rows, 1):
        lines.append(
            f"| {i} | {r['scenario']} | {'PASS' if r['passed'] else '**FAIL**'} "
            f"| {r['outcome']} | {r['class']} | {r['detect_to_proposal_s']} "
            f"| {r.get('inject_to_firing_s', '—')} | {r['reason'].replace(chr(124), '/')} |"
        )
    lines.append("")
    lines.append("Raw per-run records: [`results.json`](results.json). "
                 "Every run is also in the tamper-evident audit chain (`python -m incident_director.cli audit`).")
    lines.append("")

    out_path.write_text("\n".join(lines), encoding="utf-8")


async def _wait_quiet(settings, timeout_s: float = SETTLE_TIMEOUT_S) -> None:
    """Wait until no SLO rule is firing/pending and telemetry settles between runs."""
    watcher = AlertWatcher(settings)
    try:
        t0 = time.monotonic()
        while True:
            states = await watcher.states()
            noisy = [u for u, s in states.items() if s in ("firing", "pending")]
            if not noisy and time.monotonic() - t0 > 45:  # min settle after last noise
                return
            if time.monotonic() - t0 > timeout_s:
                print(f"[eval] WARN settle timeout; proceeding with states={states}")
                return
            await asyncio.sleep(5)
    finally:
        await watcher.close()


async def run_matrix(runs: int = 1, scenarios: list[str] | None = None, out_dir: str = "") -> int:
    """Run the graded matrix. Returns process exit code (0 iff N/N passed)."""
    # The eval needs the loop to EXECUTE so the executor verdict is gradable.
    # Double opt-in stays local to this harness invocation.
    os.environ["APPROVAL_MODE"] = "auto_approve"
    os.environ["ALLOW_AUTO_APPROVE"] = "1"

    settings = load_settings()
    problems = settings.validate_runtime()
    if problems:
        print("eval blocked:\n  - " + "\n  - ".join(problems))
        return 2

    sim = SimClient(settings)
    try:
        health = await sim.health()
        print(f"[eval] sim healthy (tick={health.get('tick')}, active={health.get('activeScenarios')})")
    finally:
        await sim.close()

    chosen = scenarios or list(SCENARIO_ALERTS)
    out = Path(out_dir) if out_dir else EVALS_DIR
    out.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []

    for run_no in range(1, runs + 1):
        for sc in chosen:
            print(f"\n[eval] === run {run_no}/{runs} :: {sc} ===")
            try:
                result, meta = await run_scenario_once(sc)
            except Exception as e:  # harness-level failure = failed run, keep going
                print(f"[eval] run raised: {e}")
                rows.append({
                    "run": run_no, "scenario": sc, "passed": False,
                    "outcome": "harness_error", "class": "", "reason": f"harness error: {e}",
                    "detect_to_proposal_s": None,
                })
                await _settle_after_failure(settings)
                continue

            g = grade_run(sc, result, meta)
            print(f"[eval] grade: {'PASS' if g.passed else 'FAIL'} — {g.reason}")
            rows.append({
                "run": run_no,
                "scenario": sc,
                "passed": g.passed,
                "outcome": result.outcome,
                "class": result.proposal.remediation_class if result.proposal else "",
                "reason": g.reason,
                "detect_to_proposal_s": result.detect_to_proposal_s,
                "proposal": result.proposal.model_dump() if result.proposal else None,
                "gate": result.gate.audit_dict if result.gate else None,
                "run_id": result.run_id,
                **meta,
            })
            await _wait_quiet(settings)

    passed = sum(1 for r in rows if r["passed"])
    total = len(rows)
    (out / "results.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    write_report(rows, runs, out / "report.md")
    print(f"\n[eval] {passed}/{total} passed — report: {out / 'report.md'}")
    return 0 if passed == total and total > 0 else 1


async def _settle_after_failure(settings) -> None:
    """Best-effort cleanup after a raised run: stop scenarios, wait quiet."""
    sim = SimClient(settings)
    try:
        await sim.stop_all()
    except Exception as e:
        print(f"[eval] WARN cleanup stop_all failed: {e}")
    finally:
        await sim.close()
    await _wait_quiet(settings)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--runs", type=int, default=1)
    p.add_argument("--scenarios", default="", help="comma-separated subset of the 6 scenarios")
    p.add_argument("--out", default="", help="output dir (default: evals/)")
    args = p.parse_args(argv)
    scenarios = [s.strip() for s in args.scenarios.split(",") if s.strip()] or None
    return asyncio.run(run_matrix(runs=args.runs, scenarios=scenarios, out_dir=args.out))


if __name__ == "__main__":
    sys.exit(main())
