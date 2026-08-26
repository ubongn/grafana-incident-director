"""Unit tests: approval gate."""

import pytest

from incident_director.gate import ApprovalGate, AUTO_APPROVE, REFUSE_UNATTENDED
from incident_director.models import RemediationProposal


def proposal(action="execute", cls="drain_cdn_edge"):
    return RemediationProposal(
        action=action,
        remediation_class=cls,
        params={"edge": "cdn-fra1"} if cls == "drain_cdn_edge" else {},
        rationale="test",
    )


def answers(*seq):
    it = iter(seq)
    return lambda _prompt: next(it)


def test_interactive_explicit_yes():
    gate = ApprovalGate(prompt_fn=answers("y"))
    assert gate.decide(proposal()).approved


def test_interactive_enter_denies():
    gate = ApprovalGate(prompt_fn=answers(""))
    d = gate.decide(proposal())
    assert not d.approved
    assert d.decided_by == "human"


def test_interactive_n_denies():
    gate = ApprovalGate(prompt_fn=answers("n"))
    assert not gate.decide(proposal()).approved


def test_interactive_garbage_denies():
    gate = ApprovalGate(prompt_fn=answers("yes please"))
    assert not gate.decide(proposal()).approved


def test_interactive_uppercase_yes():
    gate = ApprovalGate(prompt_fn=answers("Y"))
    assert gate.decide(proposal()).approved


def test_refuse_unattended_never_executes():
    gate = ApprovalGate(mode=REFUSE_UNATTENDED)
    d = gate.decide(proposal())
    assert not d.approved
    assert "unattended" in d.reason


def test_auto_approve_mode():
    gate = ApprovalGate(mode=AUTO_APPROVE)
    assert gate.decide(proposal()).approved


def test_no_action_proposal_needs_no_human():
    gate = ApprovalGate(prompt_fn=answers("y"))
    d = gate.decide(proposal(action="refuse", cls="none"))
    assert not d.approved
    assert d.decided_by == "mode:no-action"


def test_unknown_mode_rejected():
    with pytest.raises(ValueError):
        ApprovalGate(mode="yolo")


def test_decision_audit_shape():
    gate = ApprovalGate(prompt_fn=answers("n"))
    d = gate.decide(proposal())
    a = d.audit_dict
    assert a["approved"] is False and a["decided_by"] == "human" and a["ts"].endswith("Z")
