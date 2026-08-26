"""Unit tests: remediation registry."""

import pytest

from incident_director.actions.registry import ProposalRejected, normalize_proposal
from incident_director.models import RemediationProposal


def prop(action="execute", cls="drain_cdn_edge", params=None):
    return RemediationProposal(
        action=action, remediation_class=cls,
        params=params if params is not None else {"edge": "cdn-fra1"}, rationale="r"
    )


def test_valid_drain_edge():
    payload = normalize_proposal(prop())
    assert payload == {"action": "drain_cdn_edge", "class": "drain_cdn_edge", "params": {"edge": "cdn-fra1"}}


def test_unknown_edge_rejected():
    with pytest.raises(ProposalRejected, match="not in"):
        normalize_proposal(prop(params={"edge": "cdn-xxx9"}))


def test_missing_param_rejected():
    with pytest.raises(ProposalRejected, match="missing required param"):
        normalize_proposal(prop(params={}))


def test_illegal_chars_rejected():
    # the edge allowlist fires first; the regex guard is defense-in-depth for
    # params without vocabularies — both must reject, never execute.
    with pytest.raises(ProposalRejected):
        normalize_proposal(prop(params={"edge": "cdn-fra1; rm -rf /"}))
    forged = prop().model_copy(update={"params": {"edge; drop tables": "x"}})
    with pytest.raises(ProposalRejected, match="illegal characters"):
        normalize_proposal(forged)


def test_unknown_class_rejected():
    # pydantic Literal blocks unknown classes at the model layer already...
    with pytest.raises(Exception):
        prop(cls="reboot_world")
    # ...and the registry independently rejects forged proposals.
    forged = prop().model_copy(update={"remediation_class": "reboot_world"})
    with pytest.raises(ProposalRejected, match="unknown remediation class"):
        normalize_proposal(forged)


def test_failover_only_to_origin_b():
    payload = normalize_proposal(RemediationProposal(
        action="execute", remediation_class="failover_origin", params={"to_origin": "origin-b"}, rationale="r"))
    assert payload["params"] == {"to_origin": "origin-b"}
    with pytest.raises(ProposalRejected):
        normalize_proposal(RemediationProposal(
            action="execute", remediation_class="failover_origin",
            params={"to_origin": "origin-a"}, rationale="r"))


def test_abr_floor_requires_region_and_platform():
    good = normalize_proposal(RemediationProposal(
        action="execute", remediation_class="tighten_abr_floor",
        params={"region": "us-east", "platform": "android"}, rationale="r"))
    assert good["params"]["platform"] == "android"
    with pytest.raises(ProposalRejected):
        normalize_proposal(RemediationProposal(
            action="execute", remediation_class="tighten_abr_floor",
            params={"region": "us-east"}, rationale="r"))


def test_refusal_normalizes_to_none():
    payload = normalize_proposal(RemediationProposal(
        action="refuse", remediation_class="none", rationale="budgets intact"))
    assert payload["action"] == "none"


def test_incoherent_refusal_rejected():
    with pytest.raises(ProposalRejected, match="refusal must use class 'none'"):
        normalize_proposal(prop(action="refuse"))


def test_cannot_execute_none():
    with pytest.raises(ProposalRejected, match="cannot be executed"):
        normalize_proposal(prop(cls="none"))
