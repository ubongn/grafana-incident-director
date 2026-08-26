"""Offline arc tests: sequencing, gate enforcement, trap refusal, audit trail.

The LLM/MCP layer is faked with a scripted phase runner — these tests lock
the ORCHESTRATION contract: nothing executes without an approved gate, every
decision is audited, tool-less phases fail, and the NO-ACTION trap can only
end in a refusal.
"""

import json
from dataclasses import dataclass, field

import pytest

from incident_director.actions.executor import RemediationExecutor
from incident_director.audit import AuditLog
from incident_director.config import Settings
from incident_director.gate import ApprovalGate
from incident_director.models import RemediationProposal
from incident_director.runbook.arc import IncidentArc

DETECT = {"has_incident": True, "benign_elevation": False, "summary": "playback errors burning",
          "alerts": [{"rule_uid": "ott-playback-errors", "rule_name": "Playback error rate burning SLO",
                       "state": "firing", "severity": "critical", "labels": {}, "summary": "err>2%"}]}
DETECT_BENIGN = {"has_incident": False, "benign_elevation": True, "summary": "sessions up, budgets intact", "alerts": []}
TRIANG = {"scope": "regional", "findings": [{"signal": "err by region", "query": "q", "evidence": "us-east 6.4%", "in_budget": False}],
          "affected_regions": ["us-east"], "affected_edges": ["cdn-iad1"], "affected_origins": [],
          "affected_platforms": [], "hypotheses": [{"name": "cdn edge", "likelihood": 0.9, "rationale": "r"}],
          "summary": "one region hot"}
DIAGNOSE = {"root_cause": "cdn-iad1 upstream timeouts", "confidence": 0.9,
            "evidence": ['{service="cdn", edge="cdn-iad1"} error=upstream_fetch_timeout'],
            "remediation_class": "drain_cdn_edge", "rationale": "edge-only degradation"}
DIAGNOSE_NONE = {"root_cause": "benign load", "confidence": 0.95, "evidence": ["all ratios in budget"],
                 "remediation_class": "none", "rationale": "no budget burning"}
PROPOSAL_EXEC = {"action": "execute", "remediation_class": "drain_cdn_edge", "params": {"edge": "cdn-iad1"},
                 "rationale": "drain hot edge", "expected_effect": "err drops", "risk": "low", "rollback": "re-add edge"}
PROPOSAL_REFUSE = {"action": "refuse", "remediation_class": "none", "params": {},
                   "rationale": "SLOs intact", "expected_effect": "none", "risk": "none", "rollback": "n/a"}
REPORT = {"annotation_id": "42", "dashboard_uid": "ott-streaming-ops", "verification": "recovery seen",
          "markdown": "# report", "follow_ups": []}


@dataclass
class FakeRunner:
    script: dict
    tool_phases: tuple = ("detect", "triangulate", "diagnose", "report")
    calls: list = field(default_factory=list)
    fail_first_attempt: dict = field(default_factory=dict)  # phase -> bad output once

    async def __call__(self, phase: str, prompt: str):
        self.calls.append(phase)
        from incident_director.runbook.runner import PhaseOutput

        if self.fail_first_attempt.get(phase, 0) > 0:
            self.fail_first_attempt[phase] -= 1
            bad = "I forgot the JSON" if phase in self.tool_phases else "no json"
            return PhaseOutput(text=bad, tool_calls=["list_alert_groups"] if phase in self.tool_phases else [])

        doc = self.script[phase]
        tools = ["list_alert_groups"] if phase in self.tool_phases else []
        return PhaseOutput(text="```json\n" + json.dumps(doc) + "\n```", tool_calls=tools)


class FakeExec:
    def __init__(self):
        self.executed: list[RemediationProposal] = []

    async def execute(self, proposal):
        self.executed.append(proposal)
        from incident_director.actions.executor import ExecutionResult

        return ExecutionResult(ok=True, action=proposal.remediation_class,
                               params=dict(proposal.params), detail="sim ok", status_code=200)


def make_arc(tmp_path, script, gate_mode="interactive", prompt_answers=(), fail_first=None):
    audit = AuditLog(tmp_path / "audit")
    gate = ApprovalGate(mode=gate_mode, prompt_fn=lambda _p: next(iter(prompt_answers), "n"))
    runner = FakeRunner(script=dict(script), fail_first_attempt=dict(fail_first or {}))
    arc = IncidentArc(
        Settings(gemini_api_key="x", grafana_token="t"),
        audit, gate, FakeExec(), phase_run=runner, verbose=False,
    )
    return arc, runner, arc.executor


@pytest.mark.anyio
class TestArc:
    async def test_full_arc_executes_after_approval(self, tmp_path, anyio_backend):
        script = {"detect": DETECT, "triangulate": TRIANG, "diagnose": DIAGNOSE,
                  "remediate": PROPOSAL_EXEC, "report": REPORT}
        arc, runner, fake_exec = make_arc(tmp_path, script, prompt_answers=("y",))
        result = await arc.run("alert", "firing")

        assert runner.calls == ["detect", "triangulate", "diagnose", "remediate", "report"]
        assert result.outcome == "executed"
        assert len(fake_exec.executed) == 1
        assert result.proposal.params == {"edge": "cdn-iad1"}
        assert result.detect_to_proposal_s >= 0
        assert result.report.annotation_id == "42"

        events = [e["event"] for e in arc.audit.entries()]
        assert "run_started" in events and "proposal" in events
        assert "gate_decision" in events and "execution" in events and "run_finished" in events
        ok, detail = arc.audit.verify_chain()
        assert ok, detail

    async def test_denied_gate_executes_nothing(self, tmp_path, anyio_backend):
        script = {"detect": DETECT, "triangulate": TRIANG, "diagnose": DIAGNOSE,
                  "remediate": PROPOSAL_EXEC, "report": REPORT}
        arc, runner, fake_exec = make_arc(tmp_path, script, prompt_answers=("n",))
        result = await arc.run("alert", "firing")

        assert result.outcome == "denied"
        assert fake_exec.executed == []
        events = [e["event"] for e in arc.audit.entries()]
        assert "execution" not in events

    async def test_unattended_mode_never_executes(self, tmp_path, anyio_backend):
        script = {"detect": DETECT, "triangulate": TRIANG, "diagnose": DIAGNOSE,
                  "remediate": PROPOSAL_EXEC, "report": REPORT}
        arc, _, fake_exec = make_arc(tmp_path, script, gate_mode="refuse_unattended")
        result = await arc.run("alert", "firing")
        assert result.outcome == "denied"
        assert fake_exec.executed == []

    async def test_traffic_spike_trap_refuses(self, tmp_path, anyio_backend):
        script = {"detect": DETECT_BENIGN, "triangulate": TRIANG, "diagnose": DIAGNOSE_NONE,
                  "remediate": PROPOSAL_REFUSE, "report": REPORT}
        arc, _, fake_exec = make_arc(tmp_path, script, prompt_answers=("y",))
        result = await arc.run("operator_report", "sessions +60%")
        assert result.outcome == "refused"
        assert result.proposal.is_no_action
        assert fake_exec.executed == []
        gate_entry = [e for e in arc.audit.entries() if e["event"] == "gate_decision"][0]
        assert gate_entry["data"]["approved"] is False

    async def test_tool_less_phase_fails_then_retries(self, tmp_path, anyio_backend):
        script = {"detect": DETECT, "triangulate": TRIANG, "diagnose": DIAGNOSE,
                  "remediate": PROPOSAL_EXEC, "report": REPORT}
        arc, runner, _ = make_arc(tmp_path, script, prompt_answers=("y",),
                                  fail_first={"detect": 1})
        result = await arc.run("alert", "firing")
        assert result.outcome == "executed"
        assert runner.calls.count("detect") == 2  # retried once

    async def test_persistent_bad_output_fails_arc(self, tmp_path, anyio_backend):
        script = {"detect": DETECT, "triangulate": TRIANG, "diagnose": DIAGNOSE,
                  "remediate": PROPOSAL_EXEC, "report": REPORT}
        arc, runner, fake_exec = make_arc(tmp_path, script, fail_first={"detect": 99})
        result = await arc.run("alert", "firing")
        assert result.outcome == "failed"
        assert "detect failed" in result.error
        assert fake_exec.executed == []
        assert runner.calls == ["detect", "detect"]  # never reached later phases

    async def test_report_failure_does_not_flip_outcome(self, tmp_path, anyio_backend):
        script = {"detect": DETECT, "triangulate": TRIANG, "diagnose": DIAGNOSE,
                  "remediate": PROPOSAL_EXEC, "report": REPORT}
        arc, _, _ = make_arc(tmp_path, script, prompt_answers=("y",), fail_first={"report": 99})
        result = await arc.run("alert", "firing")
        assert result.outcome == "executed"
        assert "report phase failed" in result.report.markdown
