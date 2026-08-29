"""Unit tests for agent self-observability telemetry (no network).

Covers: sample building from a synthetic ArcResult, cost math at published
list price, Loki payload shape, and the usage aggregation added to the ADK
runner (fake events).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from incident_director.gate import GateDecision
from incident_director.models.phases import PhaseRecord, ReportResult
from incident_director.runbook.arc import ArcResult
from incident_director.runbook.runner import PhaseOutput
from incident_director import telemetry


def _result() -> ArcResult:
    phases = [
        PhaseRecord(phase="detect", ok=True, seconds=4.5, tool_calls=["alerting_manage_rules"], usage={"prompt": 1000, "candidates": 200, "thoughts": 50, "total": 1250}),
        PhaseRecord(phase="triangulate", ok=True, seconds=13.0, tool_calls=["query_prometheus", "query_prometheus"], usage={"prompt": 2000, "candidates": 400, "thoughts": 100, "total": 2500}),
        PhaseRecord(phase="remediate", ok=True, seconds=3.5, tool_calls=[], usage={"prompt": 800, "candidates": 150, "thoughts": 0, "total": 950}),
    ]
    r = ArcResult(run_id="run-test", trigger_type="alert", trigger_text="t")
    r.phases = phases
    r.gate = GateDecision(approved=False, decided_by="mode:refuse_unattended", reason="unattended", ts="2026-01-01T00:00:00Z")
    r.executed = False
    r.outcome = "denied"
    r.t_start, r.t_proposal, r.t_end = 1000.0, 1045.0, 1050.0
    r.report = ReportResult(markdown="# r")
    return r


def test_samples_shape_and_names():
    samples = telemetry.run_samples(_result(), {"scenario": "cdn-edge-degraded", "inject_to_firing_s": 210.0, "alert_rule_uid": "ott-edge-latency"}, "gemini-2.5-flash")
    by_name: dict[str, list[dict]] = {}
    for s in samples:
        assert set(s.keys()) == {"labels", "samples"}
        assert s["samples"] and isinstance(s["samples"][0]["value"], float)
        labels = s["labels"]
        assert labels["job"] == "incident-director" and labels["source"] == "agent"
        assert "__name__" in labels
        by_name.setdefault(labels["__name__"], []).append(s)
    # core families present
    assert "incident_director_phase_seconds" in by_name
    assert "incident_director_detect_to_proposal_seconds" in by_name
    assert "incident_director_detect_to_report_seconds" in by_name
    assert "incident_director_gate_decision" in by_name
    assert "incident_director_alert_brew_seconds" in by_name
    assert "incident_director_model_tokens" in by_name
    assert "incident_director_model_cost_usd" in by_name
    # per-phase seconds carry ok labels; detect has ok=true
    det = [s for s in by_name["incident_director_phase_seconds"] if s["labels"]["phase"] == "detect"]
    assert det and det[0]["labels"]["ok"] == "true" and det[0]["samples"][0]["value"] == 4.5
    # tool calls are per (phase, tool) markers
    tri = [s for s in by_name.get("incident_director_phase_tool_calls", []) if s["labels"]["phase"] == "triangulate"]
    assert len(tri) == 2  # one marker per call (query_prometheus twice)
    # gate decision label encodes mode + refusal
    assert by_name["incident_director_gate_decision"][0]["labels"]["decision"] == "mode:refuse_unattended:refused"
    # timings
    d2p = by_name["incident_director_detect_to_proposal_seconds"][0]["samples"][0]["value"]
    assert d2p == 45.0
    d2r = by_name["incident_director_detect_to_report_seconds"][0]["samples"][0]["value"]
    assert d2r == 50.0


def test_cost_math():
    # gemini-2.5-flash: $0.30/M input, $2.50/M output (thoughts billed as output)
    cost = telemetry.estimate_cost_usd({"prompt": 1_000_000, "candidates": 200_000, "thoughts": 100_000}, "gemini-2.5-flash")
    assert abs(cost - (0.30 + 0.5 + 0.25)) < 1e-9
    assert telemetry.estimate_cost_usd({}, "gemini-2.5-flash") == 0.0
    assert telemetry.estimate_cost_usd({"prompt": 100}, "unknown-model") == 0.0


def test_loki_payload_shape():
    payload = telemetry.loki_payload(_result(), {"scenario": "cdn-edge-degraded"}, "gemini-2.5-flash")
    (stream,) = payload["streams"]
    assert stream["stream"]["job"] == "incident-director"
    assert stream["stream"]["source"] == "agent"
    assert stream["stream"]["outcome"] == "denied"
    (ts, line) = stream["values"][0]
    assert ts.isdigit() and len(ts) >= 18  # ns timestamp
    import json

    parsed = json.loads(line)
    assert parsed["run_id"] == "run-test"
    assert parsed["outcome"] == "denied"
    assert parsed["detect_to_report_s"] == 50.0
    assert parsed["tokens"]["prompt"] == 3800
    assert parsed["est_cost_usd"] > 0
    assert parsed["pricing"] == telemetry.PRICING_LABEL


def test_sample_builder_rejects_garbage():
    assert telemetry._sample("x", {"k": None}, "not-a-number") is None
    s = telemetry._sample("x", {"k": "", "j": 1}, 2)
    assert s["labels"] == {"__name__": "x", "job": "incident-director", "source": "agent", "j": "1"}


def test_runner_usage_aggregation(monkeypatch):
    """Fake ADK events carry usage_metadata; the real run_phase_agent must sum."""
    import asyncio

    class U:
        def __init__(self, **kw):
            self.__dict__.update(kw)

    class E:
        def __init__(self, usage=None, final=False, text=""):
            self.usage_metadata = usage
            self._final = final
            self.content = None
            if text:
                class _C:
                    parts = [type("P", (), {"text": text})()]
                self.content = _C()

        def is_final_response(self):
            return self._final

        def get_function_calls(self):
            return None

        def get_function_responses(self):
            return None

    events = [
        E(usage=U(prompt_token_count=100, candidates_token_count=20, thoughts_token_count=5, total_token_count=125)),
        E(usage=U(prompt_token_count=50, candidates_token_count=10, thoughts_token_count=0, total_token_count=60)),
        E(usage=None, final=True, text="done"),
    ]

    class FakeSessionService:
        async def create_session(self, **kw):
            return type("S", (), {"id": "s1"})()

    class FakeRunner:
        def __init__(self, **kw):
            pass

        def run_async(self, **kw):
            async def gen():
                for e in events:
                    yield e

            return gen()

    from incident_director.runbook import runner as runner_mod

    monkeypatch.setattr(runner_mod, "Runner", FakeRunner)
    monkeypatch.setattr(runner_mod, "InMemorySessionService", FakeSessionService)

    out = asyncio.run(runner_mod.run_phase_agent(agent=object(), prompt="p", timeout_s=5))
    assert out.text == "done"
    assert out.usage == {"prompt": 150, "candidates": 30, "thoughts": 5, "total": 185}
