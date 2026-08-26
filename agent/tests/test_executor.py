"""Executor test with a mocked httpx transport (no sim needed)."""

import httpx
import pytest

from incident_director.actions.executor import RemediationExecutor
from incident_director.config import Settings
from incident_director.models import RemediationProposal


@pytest.fixture
def settings():
    return Settings(gemini_api_key="x", grafana_token="t", sim_control_url="http://sim.test")


def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.anyio
async def test_execute_posts_validated_payload(settings, anyio_backend):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = httpx.Response(200).json() if False else None
        import json as _json
        seen["payload"] = _json.loads(request.content)
        return httpx.Response(200, json={"ok": True, "action": "drain_cdn_edge"})

    executor = RemediationExecutor(settings, client=_client(handler))
    result = await executor.execute(RemediationProposal(
        action="execute", remediation_class="drain_cdn_edge",
        params={"edge": "cdn-fra1"}, rationale="r"))

    assert result.ok
    assert seen["url"].endswith("/remediate")
    assert seen["payload"] == {"action": "drain_cdn_edge", "edge": "cdn-fra1"}


@pytest.mark.anyio
async def test_execute_rejects_invalid_proposal_without_http(settings, anyio_backend):
    def handler(request):  # pragma: no cover - must not be called
        raise AssertionError("must not reach the sim")

    executor = RemediationExecutor(settings, client=_client(handler))
    result = await executor.execute(RemediationProposal(
        action="execute", remediation_class="drain_cdn_edge",
        params={"edge": "not-an-edge"}, rationale="r"))
    assert not result.ok
    assert "rejected" in result.detail


@pytest.mark.anyio
async def test_execute_sim_error_reported(settings, anyio_backend):
    def handler(request):
        return httpx.Response(400, json={"error": "no active matching scenario"})

    executor = RemediationExecutor(settings, client=_client(handler))
    result = await executor.execute(RemediationProposal(
        action="execute", remediation_class="drain_cdn_edge",
        params={"edge": "cdn-fra1"}, rationale="r"))
    assert not result.ok and result.status_code == 400


@pytest.mark.anyio
async def test_execute_transport_error(settings, anyio_backend):
    def handler(request):
        raise httpx.ConnectError("boom")

    executor = RemediationExecutor(settings, client=_client(handler))
    result = await executor.execute(RemediationProposal(
        action="execute", remediation_class="drain_cdn_edge",
        params={"edge": "cdn-fra1"}, rationale="r"))
    assert not result.ok and "transport error" in result.detail
