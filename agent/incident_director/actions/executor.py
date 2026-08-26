"""Guarded remediation executor.

Executes ONLY registry-validated payloads, ONLY after a gate approval, and
ONLY against the telemetry simulator's remediation control endpoint
(POST /remediate). Every attempt is observable by the caller for the audit
log. The executor never interprets free-form model output — structure in,
deterministic POST out.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from ..config import Settings
from .registry import ProposalRejected, normalize_proposal
from ..models import RemediationProposal


@dataclass
class ExecutionResult:
    ok: bool
    action: str
    params: dict
    detail: str = ""
    status_code: int | None = None


class RemediationExecutor:
    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        self._settings = settings
        self._client = client  # injectable for tests

    async def execute(self, proposal: RemediationProposal) -> ExecutionResult:
        try:
            payload = normalize_proposal(proposal)
        except ProposalRejected as e:
            return ExecutionResult(ok=False, action=proposal.remediation_class,
                                   params=dict(proposal.params), detail=f"rejected: {e}")

        if payload["action"] == "none":
            return ExecutionResult(ok=True, action="none", params={},
                                   detail="no-op (refusal)")

        url = f"{self._settings.sim_control_url}/remediate"
        own_client = self._client is None
        client = self._client or httpx.AsyncClient(timeout=15.0)
        try:
            resp = await client.post(url, json=payload["params"] | {"action": payload["action"]})
            detail = resp.text[:500]
            return ExecutionResult(
                ok=resp.status_code == 200,
                action=payload["action"],
                params=payload["params"],
                detail=detail,
                status_code=resp.status_code,
            )
        except httpx.HTTPError as e:
            return ExecutionResult(ok=False, action=payload["action"],
                                   params=payload["params"], detail=f"transport error: {e}")
        finally:
            if own_client:
                await client.aclose()
