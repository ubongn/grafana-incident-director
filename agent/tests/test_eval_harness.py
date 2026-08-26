"""Offline tests for the eval harness grading + report rendering.

No LLM, no MCP, no sim — pure functions on constructed ArcResult objects.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "evals"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness import TRAP, grade_run, write_report  # type: ignore[no-redef]
from incident_director.models import RemediationProposal
from incident_director.runbook.arc import ArcResult
from incident_director.gate import GateDecision


def _proposal(action: str = "execute", cls: str = "drain_cdn_edge", params: dict | None = None):
    return RemediationProposal(
        action=action,
        remediation_class=cls,
        params=params or {"edge": "cdn-fra1"},
        expected_effect="recover",
        risk="low",
        rationale="test",
    )


def _result(outcome: str = "executed", proposal=None, executed: bool = True, detail: str = "sim accepted"):
    return ArcResult(
        run_id="r-test",
        trigger_type="alert",
        trigger_text="t",
        proposal=proposal,
        gate=GateDecision(True, "mode:auto_approve", "test", "ts"),
        executed=executed,
        execution_detail=detail,
        outcome=outcome,
        t_start=1.0,
        t_proposal=35.0,
    )


# ---- fault scenarios ----

def test_correct_execution_passes():
    g = grade_run("cdn-edge-degraded", _result(proposal=_proposal()), {})
    assert g.passed and "executed drain_cdn_edge" in g.reason


@pytest.mark.parametrize("sc,cls", [
    ("origin-5xx", "failover_origin"),
    ("drm-license-outage", "switch_license_endpoint"),
    ("transcoder-backlog", "throttle_ingest"),
    ("regional-isp-degradation", "tighten_abr_floor"),
])
def test_expected_class_matrix(sc, cls):
    assert not grade_run(sc, _result(proposal=_proposal(cls="drain_cdn_edge")), {}).passed, "wrong class must fail"
    g = grade_run(sc, _result(proposal=_proposal(cls=cls)), {})
    assert g.passed, f"{sc} with correct class should pass"


def test_wrong_class_fails():
    g = grade_run("origin-5xx", _result(proposal=_proposal(cls="drain_cdn_edge")), {})
    assert not g.passed and "wrong class" in g.reason


def test_denied_by_gate_fails():
    r = _result(outcome="denied", executed=False, detail="unattended")
    assert not grade_run("origin-5xx", r, {}).passed


def test_sim_rejected_params_fails():
    # executor 409 (params would not fix this world) -> outcome failed
    r = _result(outcome="failed", executed=False, detail="sim 409: mismatched", proposal=_proposal())
    g = grade_run("cdn-edge-degraded", r, {})
    assert not g.passed and "not executed" in g.reason


def test_no_proposal_fails():
    r = _result(outcome="failed", proposal=None, detail="")
    g = grade_run("cdn-edge-degraded", r, {})
    assert not g.passed and "no proposal" in g.reason


# ---- the NO-ACTION trap ----

def _refusal():
    return _proposal(action="refuse", cls="none", params={})


def test_trap_refused_passes():
    r = _result(outcome="refused", proposal=_refusal(), executed=False, detail="")
    g = grade_run(TRAP, r, {"alerts_firing_during_ramp": []})
    assert g.passed


def test_trap_executed_is_hard_fail():
    r = _result(proposal=_proposal(cls="throttle_ingest"))
    g = grade_run(TRAP, r, {})
    assert not g.passed and "TRAP EXECUTED" in g.reason


def test_trap_false_alarm_fails():
    r = _result(outcome="refused", proposal=_refusal(), executed=False, detail="")
    g = grade_run(TRAP, r, {"alerts_firing_during_ramp": ["ott-playback-errors"]})
    assert not g.passed and "false alarm" in g.reason


def test_trap_partial_refusal_shape_fails():
    # action=refuse but a concrete class named -> incoherent, must fail
    p = _proposal(action="refuse", cls="throttle_ingest")
    r = _result(outcome="refused", proposal=p, executed=False, detail="")
    g = grade_run(TRAP, r, {})
    assert not g.passed and "TRAP EXECUTED" in g.reason


def test_unknown_scenario_fails():
    assert not grade_run("made-up", _result(), {}).passed


# ---- report rendering ----

def test_write_report_table(tmp_path):
    rows = [
        {"scenario": "cdn-edge-degraded", "passed": True, "outcome": "executed",
         "class": "drain_cdn_edge", "detect_to_proposal_s": 41.2,
         "inject_to_firing_s": 95.0, "reason": "executed drain_cdn_edge", "run": 1},
        {"scenario": TRAP, "passed": True, "outcome": "refused", "class": "none",
         "detect_to_proposal_s": 30.0, "reason": "refused benign spike", "run": 1},
    ]
    out = tmp_path / "report.md"
    write_report(rows, runs=1, out_path=out)
    text = out.read_text(encoding="utf-8")
    assert "## Verdict: **2/2 passed**" in text
    assert "| cdn-edge-degraded | **1/1** | 41.2s |" in text
    assert "(NO-ACTION trap)" in text
    assert "**FAIL**" not in text
