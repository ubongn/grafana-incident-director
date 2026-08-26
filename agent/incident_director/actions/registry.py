"""Remediation registry — the closed set of actions the director may propose.

Mirrors sim/src/remediation.js. The registry is the single source of truth the
executor validates against: unknown class, missing params, or params outside
the known world topology are rejected BEFORE anything executes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..models import RemediationProposal

REGIONS = ("eu-west", "eu-central", "us-east", "us-west", "ap-south", "ap-southeast")
PLATFORMS = ("web", "android", "ios", "tvos", "firetv")
EDGES = ("cdn-fra1", "cdn-ams1", "cdn-iad1", "cdn-sfo1", "cdn-bom1", "cdn-sin1")
ORIGINS = ("origin-a", "origin-b")
_EDGE_REGION = dict(zip(EDGES, REGIONS))


@dataclass(frozen=True)
class RemediationSpec:
    name: str
    required: tuple[str, ...] = ()
    allowed_values: dict[str, tuple[str, ...]] = field(default_factory=dict)
    description: str = ""


REGISTRY: dict[str, RemediationSpec] = {
    "drain_cdn_edge": RemediationSpec(
        name="drain_cdn_edge",
        required=("edge",),
        allowed_values={"edge": EDGES},
        description="Drain one CDN edge: shift its region's traffic to peer edges.",
    ),
    "failover_origin": RemediationSpec(
        name="failover_origin",
        required=("to_origin",),
        allowed_values={"to_origin": ("origin-b",)},
        description="Fail playback packaging over to the backup origin.",
    ),
    "switch_license_endpoint": RemediationSpec(
        name="switch_license_endpoint",
        description="Switch DRM licensing to the secondary provider endpoint.",
    ),
    "throttle_ingest": RemediationSpec(
        name="throttle_ingest",
        description="Throttle low-priority ingest and route the surge to the burst transcode pool.",
    ),
    "tighten_abr_floor": RemediationSpec(
        name="tighten_abr_floor",
        required=("region", "platform"),
        allowed_values={"region": REGIONS, "platform": PLATFORMS},
        description="Tighten the ABR bitrate floor for one region+platform cohort.",
    ),
    "none": RemediationSpec(name="none", description="No action (benign load / out of budget discipline)."),
}


class ProposalRejected(Exception):
    pass


def normalize_proposal(proposal: RemediationProposal) -> dict:
    """Validate a proposal against the registry; return executor payload.

    Raises ProposalRejected with a precise reason — the arc audits that reason.
    """
    if proposal.action == "refuse":
        if proposal.remediation_class != "none":
            # A refusal that names a concrete action class is incoherent;
            # treat as refusal of everything (nothing executes either way).
            raise ProposalRejected(
                f"refusal must use class 'none', got '{proposal.remediation_class}'"
            )
        return {"action": "none", "class": "none", "params": {}}

    if proposal.action != "execute":
        raise ProposalRejected(f"unknown action: {proposal.action!r}")

    name = proposal.remediation_class
    if name not in REGISTRY:
        raise ProposalRejected(f"unknown remediation class: {name!r}")
    spec = REGISTRY[name]
    if name == "none":
        raise ProposalRejected("class 'none' cannot be executed; action must be refuse")

    # raw guard first: key names and values must be plain identifiers
    for key, value in proposal.params.items():
        if not re.fullmatch(r"[A-Za-z0-9_.\-]+", str(key)):
            raise ProposalRejected(f"{name}: illegal characters in param key {key!r}")
        if not re.fullmatch(r"[A-Za-z0-9_.\-]+", str(value)):
            raise ProposalRejected(f"{name}: illegal characters in param '{key}'")

    params: dict[str, str] = {}
    for key in spec.required:
        value = str(proposal.params.get(key, "")).strip()
        if not value:
            raise ProposalRejected(f"{name}: missing required param '{key}'")
        allowed = spec.allowed_values.get(key)
        if allowed and value not in allowed:
            raise ProposalRejected(
                f"{name}: param '{key}' value {value!r} not in {list(allowed)}"
            )
        params[key] = value

    # optional params with known vocab
    for key, allowed in spec.allowed_values.items():
        if key in spec.required:
            continue
        value = str(proposal.params.get(key, "")).strip()
        if value and value in allowed:
            params[key] = value

    return {"action": name, "class": name, "params": params}
