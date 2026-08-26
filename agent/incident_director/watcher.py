"""Alert watcher — harness-side polling of Grafana alert state.

The AGENT reads alerts through the Grafana MCP server; this watcher is demo/
eval plumbing that decides WHEN an arc should start (an SLO rule is firing)
and marks t0 for the detect->proposal metric. It uses the plain Grafana HTTP
API with the service-account token.
"""

from __future__ import annotations

import asyncio
import time

import httpx

from .config import Settings

# rule uid -> title (provisioned in deploy/grafana/provisioning/alerting)
RULE_TITLES = {
    "ott-playback-errors": "Playback error rate burning SLO",
    "ott-rebuffer": "Rebuffer ratio above budget",
    "ott-origin-5xx": "Origin 5xx rate elevated",
    "ott-edge-latency": "CDN edge latency p95 high",
    "ott-transcoder-lag": "Transcoder lag building",
}
TITLE_TO_UID = {v: k for k, v in RULE_TITLES.items()}


class AlertWatcher:
    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        self._settings = settings
        self._own = client is None
        self._client = client or httpx.AsyncClient(timeout=10.0)

    async def _get(self, path: str) -> httpx.Response:
        return await self._client.get(
            f"{self._settings.grafana_url}{path}",
            headers={"Authorization": f"Bearer {self._settings.grafana_token}"},
        )

    async def states(self) -> dict[str, str]:
        """Map of rule uid -> aggregate state (normal/pending/firing).

        Grafana 13 removed the legacy /api/alerts endpoint; the
        Prometheus-compatible view (/api/prometheus/grafana/api/v1/alerts)
        carries one alert PER RULE INSTANCE (per edge/region/... series) with
        `labels.alertname` (the rule title) and `state` in
        {Normal, Pending, Alerting}. A rule counts as firing if ANY instance
        fires — collapsing to the last instance instead would randomly miss
        the one degraded edge sitting behind five healthy siblings.
        """
        resp = await self._get("/api/prometheus/grafana/api/v1/alerts")
        resp.raise_for_status()
        rank = {"normal": 0, "pending": 1, "firing": 2}
        out: dict[str, str] = {}
        for a in resp.json().get("data", {}).get("alerts", []):
            uid = TITLE_TO_UID.get(a.get("labels", {}).get("alertname", ""))
            if not uid:
                continue
            state = {"alerting": "firing", "pending": "pending", "normal": "normal"}.get(
                (a.get("state") or "").lower(), "unknown"
            )
            if rank.get(state, -1) >= rank.get(out.get(uid, "unknown"), -1):
                out[uid] = state
        return out

    async def firing(self) -> list[str]:
        return [uid for uid, state in (await self.states()).items() if state == "firing"]

    async def wait_firing(
        self,
        expected_uids: list[str] | None = None,
        timeout_s: float = 420.0,
        poll_s: float = 5.0,
        quiet: bool = False,
    ) -> tuple[str, float]:
        """Wait until at least one expected rule (or any SLO rule) is firing.

        Returns (rule_uid, waited_seconds). Raises TimeoutError otherwise.
        """
        t0 = time.monotonic()
        last = {}
        while True:
            states = await self.states()
            firing = [u for u, s in states.items() if s == "firing"]
            if expected_uids:
                hit = [u for u in firing if u in expected_uids]
            else:
                hit = firing
            if hit:
                return hit[0], round(time.monotonic() - t0, 1)
            last = states
            if time.monotonic() - t0 > timeout_s:
                raise TimeoutError(f"no alert firing after {timeout_s}s; states={last}")
            if not quiet:
                pending = [u for u, s in states.items() if s == "pending"]
                print(f"    waiting for alert... firing={firing} pending={pending}", flush=True)
            await asyncio.sleep(poll_s)

    async def wait_quiet(
        self, timeout_s: float = 300.0, poll_s: float = 8.0, quiet: bool = False
    ) -> bool:
        """Wait until no SLO rule is firing (recovery between eval runs)."""
        t0 = time.monotonic()
        while True:
            firing = await self.firing()
            if not firing:
                return True
            if time.monotonic() - t0 > timeout_s:
                if not quiet:
                    print(f"    WARN: still firing after {timeout_s}s: {firing}", flush=True)
                return False
            if not quiet:
                print(f"    waiting for alerts to clear... firing={firing}", flush=True)
            await asyncio.sleep(poll_s)

    async def close(self) -> None:
        if self._own:
            await self._client.aclose()
