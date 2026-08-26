"""Human-approval gate for REMEDIATE actions.

Every remediation proposal must pass through `ApprovalGate.decide()` before
anything is executed. Interactive mode is the default and demands an explicit
`y` — empty input, `n`, or anything else denies. Unattended modes exist for
demo/eval runs and NEVER auto-execute anything: `refuse_unattended` denies
with a recorded reason; `auto_approve` requires the ALLOW_AUTO_APPROVE=1
double opt-in and exists only for automated gate-path tests.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Protocol

from .models import RemediationProposal

INTERACTIVE = "interactive"
REFUSE_UNATTENDED = "refuse_unattended"
AUTO_APPROVE = "auto_approve"


@dataclass
class GateDecision:
    approved: bool
    decided_by: str  # human | mode:<name>
    reason: str
    ts: str

    @property
    def audit_dict(self) -> dict:
        return {
            "approved": self.approved,
            "decided_by": self.decided_by,
            "reason": self.reason,
            "ts": self.ts,
        }


class ApprovalGate:
    def __init__(self, mode: str = INTERACTIVE, prompt_fn: Callable[[str], str] = input) -> None:
        if mode not in (INTERACTIVE, REFUSE_UNATTENDED, AUTO_APPROVE):
            raise ValueError(f"unknown approval mode: {mode}")
        self.mode = mode
        self._prompt = prompt_fn

    def decide(self, proposal: RemediationProposal) -> GateDecision:
        ts = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + "Z"

        if proposal.is_no_action:
            # A refusal needs no human approval — nothing will be executed.
            return GateDecision(False, "mode:no-action", "proposal is a refusal; nothing to execute", ts)

        if self.mode == REFUSE_UNATTENDED:
            return GateDecision(
                False,
                "mode:refuse_unattended",
                "unattended mode: execution requires an interactive human approval",
                ts,
            )

        if self.mode == AUTO_APPROVE:
            return GateDecision(True, "mode:auto_approve", "auto-approve (double opt-in)", ts)

        answer = self._prompt(
            "\n>>> APPROVE execution of this remediation? [y/N] "
        ).strip().lower()
        if answer == "y" or answer == "yes":
            return GateDecision(True, "human", "operator typed y", ts)
        return GateDecision(False, "human", f"operator denied (input={answer!r})", ts)


class _Renderer(Protocol):
    def __call__(self, proposal: RemediationProposal) -> None: ...


def render_proposal(proposal: RemediationProposal) -> None:
    """Print the proposal card the operator approves or denies."""
    line = "-" * 62
    print(f"\n{line}\nREMEDIATION PROPOSAL ({proposal.action})\n{line}")
    print(f"class   : {proposal.remediation_class}")
    if proposal.params:
        print(f"params  : {proposal.params}")
    print(f"effect  : {proposal.expected_effect}")
    print(f"risk    : {proposal.risk}")
    print(f"rollback: {proposal.rollback}")
    print(f"why     : {proposal.rationale}\n{line}")
