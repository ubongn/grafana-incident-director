// Deterministic fault-injection control API (:8790).
//   GET  /health                -> sim status
//   GET  /scenarios             -> registry + active
//   POST /scenarios/start       -> {"name": "...", "params": {...}}
//   POST /scenarios/stop        -> {"id": "..."} or {"name": "..."}
// This is the demo's "inject synthetic incident" lever.

import http from "node:http";
import { SCENARIOS, ScenarioInstance, listScenarios } from "./scenarios.js";
import { REMEDIATIONS, applyRemediation } from "./remediation.js";

export function startControlServer({ port, active, simRef, stats = null }) {
  const server = http.createServer((req, res) => {
    const url = new URL(req.url, "http://localhost");
    const send = (code, obj) => {
      res.writeHead(code, { "Content-Type": "application/json" });
      res.end(JSON.stringify(obj));
    };

    if (req.method === "GET" && url.pathname === "/health") {
      return send(200, {
        ok: true,
        tick: simRef.tick,
        startedAt: simRef.startedAt,
        activeScenarios: active.map((s) => ({ id: s.id, name: s.name, ageSeconds: Math.round(s.ageSeconds(Date.now())) })),
      });
    }

    if (req.method === "GET" && url.pathname === "/scenarios") {
      return send(200, { scenarios: listScenarios(), active });
    }

    if (req.method === "POST" && url.pathname === "/scenarios/start") {
      let body = "";
      req.on("data", (c) => (body += c));
      req.on("end", () => {
        try {
          const { name, params } = JSON.parse(body || "{}");
          if (!name || !SCENARIOS[name]) {
            return send(404, { error: `unknown scenario: ${name}`, available: Object.keys(SCENARIOS) });
          }
          const sc = new ScenarioInstance(name, SCENARIOS[name], Date.now(), params);
          active.push(sc);
          send(200, { ok: true, scenario: { id: sc.id, name: sc.name, params: sc.params } });
        } catch (e) {
          send(400, { error: String(e) });
        }
      });
      return;
    }

    if (req.method === "POST" && url.pathname === "/scenarios/stop") {
      let body = "";
      req.on("data", (c) => (body += c));
      req.on("end", () => {
        try {
          const { id, name } = JSON.parse(body || "{}");
          const idx = active.findIndex((s) => (id && s.id === id) || (!id && name && s.name === name));
          if (idx === -1) return send(404, { error: "scenario not active" });
          const [stopped] = active.splice(idx, 1);
          send(200, { ok: true, stopped: { id: stopped.id, name: stopped.name } });
        } catch (e) {
          send(400, { error: String(e) });
        }
      });
      return;
    }

    if (req.method === "POST" && url.pathname === "/remediate") {
      let body = "";
      req.on("data", (c) => (body += c));
      req.on("end", () => {
        try {
          const payload = JSON.parse(body || "{}");
          const result = applyRemediation(payload, active);
          send(result.status, result.body);
        } catch (e) {
          send(400, { error: String(e) });
        }
      });
      return;
    }

    if (req.method === "GET" && url.pathname === "/remediations") {
      return send(200, {
        available: Object.keys(REMEDIATIONS),
        suppressed: active
          .filter((s) => s.suppression)
          .map((s) => ({ id: s.id, name: s.name, appliedAt: new Date(s.suppression.appliedAt).toISOString() })),
      });
    }

    // push-layer health: series cardinality per tick, ok/fail counters, endpoints
    if (req.method === "GET" && url.pathname === "/stats") {
      if (!stats) return send(404, { error: "stats not wired" });
      return send(200, {
        ok: stats.promFail === 0 && stats.lokiFail === 0,
        tick: simRef.tick,
        ...stats,
      });
    }

    send(404, { error: "not found" });
  });

  return new Promise((resolve) => server.listen(port, "127.0.0.1", () => resolve(server)));
}
