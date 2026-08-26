"""Thin async client for the telemetry simulator's control API (:8790).

Used by the CLI, demo and eval harness to inject faults and stop them.
This is test-harness plumbing — the AGENT itself only sees the stack
through the Grafana MCP server.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from .config import Settings


@dataclass
class ScenarioRun:
    id: str
    name: str
    params: dict


class SimError(Exception):
    pass


class SimClient:
    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        self._base = settings.sim_control_url
        self._own = client is None
        self._client = client or httpx.AsyncClient(timeout=15.0)

    async def _req(self, method: str, path: str, json: dict | None = None) -> dict:
        try:
            resp = await self._client.request(method, f"{self._base}{path}", json=json)
        except httpx.HTTPError as e:
            raise SimError(f"sim unreachable ({e})") from None
        if resp.status_code >= 400:
            raise SimError(f"sim {method} {path} -> {resp.status_code}: {resp.text[:200]}")
        return resp.json()

    async def health(self) -> dict:
        return await self._req("GET", "/health")

    async def scenarios(self) -> dict:
        return await self._req("GET", "/scenarios")

    async def start(self, name: str, params: dict | None = None) -> ScenarioRun:
        data = await self._req("POST", "/scenarios/start", {"name": name, "params": params or {}})
        sc = data.get("scenario", {})
        return ScenarioRun(id=sc.get("id", ""), name=sc.get("name", name), params=sc.get("params", {}))

    async def stop(self, *, id: str | None = None, name: str | None = None) -> dict:
        return await self._req("POST", "/scenarios/stop", {"id": id, "name": name})

    async def stop_all(self) -> int:
        data = await self._req("GET", "/scenarios")
        stopped = 0
        for sc in data.get("active", []):
            await self.stop(id=sc.get("id"))
            stopped += 1
        return stopped

    async def close(self) -> None:
        if self._own:
            await self._client.aclose()
