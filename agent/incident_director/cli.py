"""incident-director CLI.

Subcommands:
  run     -- wait for (or inject) an incident and run one arc interactively
  demo    -- unattended camera-friendly run: scenario -> alert -> diagnosis ->
             proposal (gate auto-refuses execution in unattended mode)
  eval    -- run the graded eval matrix (see evals/)
  probe   -- verify Grafana MCP toolset connectivity + tool filters
  audit   -- inspect / verify the append-only audit chain
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from . import __version__
from .audit import AuditLog
from .config import load_settings
from .pipeline import SCENARIO_ALERTS, build_arc, run_scenario_once
from .runbook.agents import build_phase_agent, close_agent_tools
from .runbook.runner import run_phase_agent


def _cmd_run(args: argparse.Namespace) -> int:
    async def go() -> int:
        if args.scenario:
            result, _ = await run_scenario_once(args.scenario, json.loads(args.params or "{}"))
        else:
            arc, settings = build_arc(verbose=True)
            result = await arc.run("alert", "Operator asked for an assessment of current alert state.")
            from .telemetry import emit_run

            emit_run(result, {"scenario": "manual"}, settings)
        if result.report and result.report.markdown:
            print("\n" + "=" * 62 + "\nINCIDENT REPORT\n" + "=" * 62)
            print(result.report.markdown)
        print(f"\noutcome={result.outcome} detect->proposal={result.detect_to_proposal_s}s run_id={result.run_id}")
        return 0 if result.outcome in ("executed", "refused", "denied") else 1

    return asyncio.run(go())


def _cmd_demo(args: argparse.Namespace) -> int:
    async def go() -> int:
        result, meta = await run_scenario_once(args.scenario, demo=True)
        print("\n" + "#" * 62)
        print("DEMO SUMMARY")
        print("#" * 62)
        print(json.dumps({**meta, "detect_to_proposal_s": result.detect_to_proposal_s,
                          "outcome": result.outcome}, indent=2))
        if result.report and result.report.markdown:
            print("\n" + result.report.markdown)
        ok = result.outcome == "refused" if args.scenario == "traffic-spike" else result.outcome in ("executed", "denied", "refused")
        return 0 if ok else 1

    return asyncio.run(go())


def _cmd_probe(args: argparse.Namespace) -> int:
    async def go() -> int:
        settings = load_settings()
        problems = settings.validate_runtime()
        if problems:
            print("blocked:\n  - " + "\n  - ".join(problems))
            return 2
        from .config import apply_ai_env

        apply_ai_env(settings)
        command, argv = settings.mcp_resolved_command
        print(f"MCP launch: {command} {' '.join(argv)}  ->  {settings.grafana_url}")
        agent = build_phase_agent(settings, args.phase)
        try:
            out = await run_phase_agent(
                agent,
                "Call alerting_manage_rules (operation=list) and reply with a one-line "
                "summary of alert rule states as JSON: {\"summary\": \"...\"}",
                timeout_s=90.0,
            )
            print(f"tool calls: {out.tool_calls}")
            print(f"response  : {out.text[:600]}")
            return 0 if out.tool_calls else 1
        finally:
            await close_agent_tools(agent)

    return asyncio.run(go())


def _cmd_audit(args: argparse.Namespace) -> int:
    settings = load_settings()
    log = AuditLog(settings.audit_dir)
    ok, detail = log.verify_chain()
    print(f"audit chain: {'OK' if ok else 'TAMPERED'} ({detail}) @ {log.path}")
    if args.tail:
        for entry in log.tail(args.tail):
            print(json.dumps(entry)[:240])
    return 0 if ok else 1


def _cmd_eval(args: argparse.Namespace) -> int:
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[2] / "evals"))
    from harness import run_matrix  # type: ignore[no-redef]

    scenarios = [s.strip() for s in args.scenarios.split(",") if s.strip()] if args.scenarios else None
    return asyncio.run(run_matrix(runs=args.runs, scenarios=scenarios, out_dir=args.out))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="incident-director", description=__doc__)
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_run = sub.add_parser("run", help="run one arc interactively (y/N gate)")
    p_run.add_argument("--scenario", choices=sorted(SCENARIO_ALERTS), default=None,
                       help="inject this sim scenario first (else wait for any firing alert)")
    p_run.add_argument("--params", default="{}", help="scenario params JSON")
    p_run.set_defaults(fn=_cmd_run)

    p_demo = sub.add_parser("demo", help="unattended demo run (stops at proposal)")
    p_demo.add_argument("--scenario", choices=sorted(SCENARIO_ALERTS), default="cdn-edge-degraded")
    p_demo.set_defaults(fn=_cmd_demo)

    p_probe = sub.add_parser("probe", help="verify the Grafana MCP toolset path")
    p_probe.add_argument("--phase", default="detect", choices=["detect", "triangulate", "diagnose", "report"])
    p_probe.set_defaults(fn=_cmd_probe)

    p_audit = sub.add_parser("audit", help="verify / inspect the audit chain")
    p_audit.add_argument("--tail", type=int, default=0)
    p_audit.set_defaults(fn=_cmd_audit)

    p_eval = sub.add_parser("eval", help="run the graded eval matrix")
    p_eval.add_argument("--runs", type=int, default=1)
    p_eval.add_argument("--scenarios", default="")
    p_eval.add_argument("--out", default="")
    p_eval.set_defaults(fn=_cmd_eval)

    args = parser.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
