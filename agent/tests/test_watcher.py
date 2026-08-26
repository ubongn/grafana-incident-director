"""Offline tests for the alert watcher's state aggregation.

Regression guards for the two bugs found live on Grafana 13:
1. per-instance collapse must take the WORST instance state (one degraded
   edge behind five healthy siblings is still a firing rule);
2. rule titles must match the provisioned yaml exactly.

No pytest-asyncio in the offline venv — async bodies run via asyncio.run.
"""

from __future__ import annotations

import asyncio

import httpx

from incident_director.config import Settings
from incident_director.watcher import RULE_TITLES, AlertWatcher


def _make(alerts: list[dict]) -> AlertWatcher:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "success", "data": {"alerts": alerts}})

    return AlertWatcher(Settings(), client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))


def _edge_alert(edge: str, state: str) -> dict:
    return {
        "labels": {"alertname": RULE_TITLES["ott-edge-latency"], "edge": edge},
        "state": state,
        "annotations": {},
    }


def test_one_firing_instance_among_normal_siblings_is_firing():
    """cdn-fra1 Alerting + 5 healthy edges (any order) => rule firing."""
    healthy = [_edge_alert(e, "Normal") for e in ("cdn-ams1", "cdn-bom1", "cdn-iad1", "cdn-sfo1", "cdn-sin1")]

    async def check(alerts):
        w = _make(alerts)
        assert (await w.states())["ott-edge-latency"] == "firing"
        assert await w.firing() == ["ott-edge-latency"]

    asyncio.run(check([_edge_alert("cdn-fra1", "Alerting"), *healthy]))
    asyncio.run(check([*healthy, _edge_alert("cdn-fra1", "Alerting")]))


def test_all_normal_is_not_firing():
    async def check():
        w = _make([_edge_alert(e, "Normal") for e in ("cdn-fra1", "cdn-ams1")])
        assert (await w.states())["ott-edge-latency"] == "normal"
        assert await w.firing() == []

    asyncio.run(check())


def test_pending_beats_normal_but_loses_to_firing():
    async def check_pending():
        w = _make([_edge_alert("cdn-fra1", "Pending"), _edge_alert("cdn-ams1", "Normal")])
        assert (await w.states())["ott-edge-latency"] == "pending"

    async def check_firing_wins():
        w = _make([_edge_alert("cdn-fra1", "Pending"), _edge_alert("cdn-ams1", "Alerting")])
        assert (await w.states())["ott-edge-latency"] == "firing"

    asyncio.run(check_pending())
    asyncio.run(check_firing_wins())


def test_rule_titles_match_provisioned_yaml():
    expected = {
        "ott-playback-errors": "Playback error rate burning SLO",
        "ott-rebuffer": "Rebuffer ratio above budget",
        "ott-origin-5xx": "Origin 5xx rate elevated",
        "ott-edge-latency": "CDN edge latency p95 high",
        "ott-transcoder-lag": "Transcoder lag building",
    }
    assert RULE_TITLES == expected


def test_wait_firing_returns_expected_uid():
    alerts = [
        {"labels": {"alertname": RULE_TITLES["ott-playback-errors"], "region": "eu-west"},
         "state": "Alerting", "annotations": {}},
    ]

    async def check():
        w = _make(alerts)
        uid, waited = await w.wait_firing(["ott-playback-errors"], timeout_s=2)
        assert uid == "ott-playback-errors" and waited < 2

    asyncio.run(check())
