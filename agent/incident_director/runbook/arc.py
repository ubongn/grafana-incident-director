"""The incident arc: DETECT -> TRIANGULATE -> DIAGNOSE -> REMEDIATE -> REPORT.

Deterministic orchestration around LLM phase agents:
- fixed phase order; each phase output is schema-validated before the next
  phase runs (one retry per phase on invalid output);
- tool phases MUST call at least one Grafana MCP tool or the phase fails —
  evidence-first is enforced, not encouraged;
- REMEDIATE produces a proposal that is ALWAYS audited, then gated. Without
  an explicit human approval nothing executes;
- REPORT posts the annotation and verifies.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Awaitable, Callable

from ..actions.executor import RemediationExecutor
from ..actions.registry import ProposalRejected, normalize_proposal
from ..audit import AuditLog
from ..config import Settings
from ..gate import ApprovalGate, GateDecision, render_proposal
from ..models import (
    DetectionResult,
    DiagnosisResult,
    PhaseRecord,
    RemediationProposal,
    ReportResult,
    TriangulationResult,
)
from . import prompts
from .agents import build_phase_agent, close_agent_tools
from .parse import PhaseParseError, validate
from .runner import PhaseOutput, run_phase_agent

PhaseRunFn = Callable[[str, str], Awaitable[PhaseOutput]]


@dataclass
class ArcResult:
    run_id: str
    trigger_type: str
    trigger_text: str
    phases: list[PhaseRecord] = field(default_factory=list)
    detection: DetectionResult | None = None
    triangulation: TriangulationResult | None = None
    diagnosis: DiagnosisResult | None = None
    proposal: RemediationProposal | None = None
    gate: GateDecision | None = None
    executed: bool = False
    execution_detail: str = ""
    report: ReportResult | None = None
    outcome: str = "failed"  # executed | refused | denied | failed
    error: str = ""
    t_start: float = 0.0
    t_proposal: float = 0.0
    t_end: float = 0.0

    @property
    def detect_to_proposal_s(self) -> float:
        if self.t_proposal and self.t_start:
            return round(self.t_proposal - self.t_start, 2)
        return -1.0

    def audit_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "trigger": {"type": self.trigger_type, "text": self.trigger_text[:500]},
            "outcome": self.outcome,
            "error": self.error,
            "detect_to_proposal_s": self.detect_to_proposal_s,
            "phases": [p.model_dump() for p in self.phases],
            "proposal": self.proposal.model_dump() if self.proposal else None,
            "gate": self.gate.audit_dict if self.gate else None,
            "executed": self.executed,
            "report_annotation_id": self.report.annotation_id if self.report else "",
        }


TOOL_PHASES = ("detect", "triangulate", "diagnose", "report")


class IncidentArc:
    def __init__(
        self,
        settings: Settings,
        audit: AuditLog,
        gate: ApprovalGate,
        executor: RemediationExecutor,
        phase_run: PhaseRunFn | None = None,
        verbose: bool = False,
    ) -> None:
        self.settings = settings
        self.audit = audit
        self.gate = gate
        self.executor = executor
        self._custom_phase_run = phase_run
        self.verbose = verbose

    def _say(self, msg: str) -> None:
        if self.verbose:
            print(msg, flush=True)

    # ------------------------------------------------------------------

    async def _default_phase_run(self, phase: str, prompt: str) -> PhaseOutput:
        agent = build_phase_agent(self.settings, phase)
        try:
            return await run_phase_agent(agent, prompt, self.settings.phase_timeout_s)
        finally:
            await close_agent_tools(agent)

    def _phase_run(self, phase: str, prompt: str) -> Awaitable[PhaseOutput]:
        if self._custom_phase_run is not None:
            return self._custom_phase_run(phase, prompt)
        return self._default_phase_run(phase, prompt)

    async def _run_phase(self, phase: str, prompt: str, model_cls, run_id: str, require_tools: bool):
        """Run one phase with retry; returns (validated, PhaseRecord)."""
        attempts_allowed = 1 + max(0, self.settings.phase_retries)
        last_error = ""
        record = PhaseRecord(phase=phase, ok=False, seconds=0.0)
        result = None
        for attempt in range(1, attempts_allowed + 1):
            t0 = time.monotonic()
            try:
                output = await self._phase_run(phase, prompt)
            except Exception as e:  # runner/transport failure
                last_error = f"runner error: {e}"
                record = PhaseRecord(
                    phase=phase, ok=False, seconds=round(time.monotonic() - t0, 2),
                    attempts=attempt, error=last_error[:300],
                )
                continue
            record = PhaseRecord(
                phase=phase,
                ok=False,
                seconds=round(time.monotonic() - t0, 2),
                tool_calls=output.tool_calls,
                attempts=attempt,
            )
            if require_tools and not output.tool_calls:
                last_error = "no Grafana MCP tool calls made"
                record.error = last_error
                self._say(f"  [{phase}] attempt {attempt}: {last_error}; retrying")
                prompt = _retry_prompt(prompt, last_error)
                continue
            try:
                result = validate(model_cls, output.text)
            except PhaseParseError as e:
                last_error = str(e)
                record.error = last_error[:300]
                self._say(f"  [{phase}] attempt {attempt}: invalid output ({e}); retrying")
                prompt = _retry_prompt(prompt, last_error)
                continue
            record.ok = True
            record.error = ""
            break

        self.audit.append(
            "phase_completed" if record.ok else "phase_failed",
            run_id,
            phase=phase,
            seconds=record.seconds,
            attempts=record.attempts,
            tool_calls=record.tool_calls,
            error=record.error,
        )
        return result, record

    # ------------------------------------------------------------------

    async def run(self, trigger_type: str, trigger_text: str) -> ArcResult:
        run_id = f"run-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
        result = ArcResult(run_id=run_id, trigger_type=trigger_type, trigger_text=trigger_text)
        self.audit.append("run_started", run_id, trigger={"type": trigger_type, "text": trigger_text[:500]})
        self._say(f"\n=== incident arc {run_id} (trigger: {trigger_type}) ===")
        result.t_start = time.time()

        try:
            # DETECT -----------------------------------------------------
            self._say("[detect] reading alert state through Grafana MCP ...")
            detection, rec = await self._run_phase(
                "detect",
                prompts.detect_prompt(trigger_type, trigger_text),
                DetectionResult,
                run_id,
                require_tools=True,
            )
            result.phases.append(rec)
            if detection is None:
                result.error = f"detect failed: {rec.error}"
                return self._finish(result, "failed")
            result.detection = detection
            self._say(f"[detect] {detection.summary}")

            # TRIANGULATE -------------------------------------------------
            self._say("[triangulate] quantifying blast radius ...")
            triangulation, rec = await self._run_phase(
                "triangulate",
                prompts.triangulate_prompt(detection.model_dump_json(), trigger_text),
                TriangulationResult,
                run_id,
                require_tools=True,
            )
            result.phases.append(rec)
            if triangulation is None:
                result.error = f"triangulate failed: {rec.error}"
                return self._finish(result, "failed")
            result.triangulation = triangulation
            self._say(f"[triangulate] scope={triangulation.scope}: {triangulation.summary}")

            # DIAGNOSE ----------------------------------------------------
            self._say("[diagnose] pulling Loki evidence ...")
            diagnosis, rec = await self._run_phase(
                "diagnose",
                prompts.diagnose_prompt(triangulation.model_dump_json()),
                DiagnosisResult,
                run_id,
                require_tools=True,
            )
            result.phases.append(rec)
            if diagnosis is None:
                result.error = f"diagnose failed: {rec.error}"
                return self._finish(result, "failed")
            result.diagnosis = diagnosis
            self._say(f"[diagnose] {diagnosis.root_cause} (conf={diagnosis.confidence})")

            # REMEDIATE (propose) ----------------------------------------
            self._say("[remediate] drafting proposal ...")
            proposal, rec = await self._run_phase(
                "remediate",
                prompts.remediate_prompt(
                    diagnosis.model_dump_json(), triangulation.model_dump_json()
                ),
                RemediationProposal,
                run_id,
                require_tools=False,
            )
            result.phases.append(rec)
            result.t_proposal = time.time()
            if proposal is None:
                result.error = f"remediate failed: {rec.error}"
                return self._finish(result, "failed")
            result.proposal = proposal
            self.audit.append(
                "proposal",
                run_id,
                phase="remediate",
                action=proposal.action,
                remediation_class=proposal.remediation_class,
                params=proposal.params,
                rationale=proposal.rationale[:1000],
                detect_to_proposal_s=result.detect_to_proposal_s,
            )
            self._say(
                f"[remediate] proposal: {proposal.action} / {proposal.remediation_class} "
                f"{proposal.params} ({result.detect_to_proposal_s}s detect->proposal)"
            )

            # GATE ---------------------------------------------------------
            render_proposal(proposal)
            decision = self.gate.decide(proposal)
            result.gate = decision
            self.audit.append("gate_decision", run_id, phase="gate", **decision.audit_dict)
            self._say(f"[gate] approved={decision.approved} by {decision.decided_by}")

            # EXECUTE (only on approval) -----------------------------------
            if decision.approved and not proposal.is_no_action:
                execution = await self.executor.execute(proposal)
                result.executed = execution.ok
                result.execution_detail = execution.detail
                self.audit.append(
                    "execution",
                    run_id,
                    phase="execute",
                    action=execution.action,
                    params=execution.params,
                    ok=execution.ok,
                    status_code=execution.status_code,
                    detail=execution.detail[:500],
                )
                if not execution.ok:
                    result.error = f"execution failed: {execution.detail[:200]}"
                    return self._finish(result, "failed")

            # REPORT -------------------------------------------------------
            self._say("[report] posting annotation + verifying ...")
            run_context = self._report_context(result)
            report, rec = await self._run_phase(
                "report",
                prompts.report_prompt(
                    run_context, result.executed, result.execution_detail or "nothing executed"
                ),
                ReportResult,
                run_id,
                require_tools=True,
            )
            result.phases.append(rec)
            result.report = report
            if report is None:
                # The loop closed; a weak report must not flip the outcome.
                self._say(f"[report] report phase failed: {rec.error}")
                report = ReportResult(markdown="*(report phase failed)*")
                result.report = report

            if proposal.is_no_action:
                outcome = "refused"
            elif decision.approved and result.executed:
                outcome = "executed"
            else:
                outcome = "denied"
            return self._finish(result, outcome)

        except Exception as e:  # noqa: BLE001 - the arc must always audit its death
            result.error = f"unhandled: {e}"
            return self._finish(result, "failed")

    # --------------------------------------------------------------------

    def _report_context(self, result: ArcResult) -> str:
        bits = [
            f"run {result.run_id}",
            f"trigger: {result.trigger_type}",
        ]
        if result.detection:
            bits.append(f"detection: {result.detection.summary}")
        if result.triangulation:
            bits.append(f"scope: {result.triangulation.scope}; regions={result.triangulation.affected_regions}")
        if result.diagnosis:
            bits.append(f"diagnosis: {result.diagnosis.root_cause}")
        if result.proposal:
            bits.append(
                f"proposal: {result.proposal.action} {result.proposal.remediation_class} {result.proposal.params}"
            )
        if result.gate:
            bits.append(f"gate: approved={result.gate.approved} by {result.gate.decided_by}")
        return " | ".join(bits)[:2500]

    def _finish(self, result: ArcResult, outcome: str) -> ArcResult:
        result.outcome = outcome
        result.t_end = time.time()
        self.audit.append(
            "run_finished",
            result.run_id,
            outcome=outcome,
            error=result.error,
            detect_to_proposal_s=result.detect_to_proposal_s,
        )
        self._say(f"=== arc {result.run_id} -> {outcome} ===\n")
        return result


def _retry_prompt(prompt: str, reason: str) -> str:
    return (
        prompt
        + f"\n\nIMPORTANT: your previous answer was rejected ({reason}). "
        + "Call at least one Grafana MCP tool and reply with ONLY the required JSON object."
    )
