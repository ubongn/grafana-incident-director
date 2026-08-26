// OTT telemetry simulator — main loop.
// Every TICK_MS: compute one deterministic tick, remote-write Prometheus
// samples, push Loki log lines. Fault injection via control API (:8790).

import { computeTick, buildSamples } from "./metrics.js";
import { buildLogLines } from "./logs.js";
import { makePromPusher, makeLokiPusher } from "./push.js";
import { startControlServer } from "./control.js";

const env = (k, d) => process.env[k] || d;
const PROM_URL = env("PROMETHEUS_REMOTE_WRITE_URL", "http://localhost:9090/api/v1/write");
const LOKI_URL = env("LOKI_PUSH_URL", "http://localhost:3100/loki/api/v1/push");
const PORT = parseInt(env("SIM_CONTROL_PORT", "8790"), 10);
const TICK_MS = parseInt(env("TICK_MS", "5000"), 10);

const active = [];
const counters = Object.create(null);
const simRef = { tick: 0, startedAt: new Date().toISOString() };

const promPush = makePromPusher(PROM_URL);
const lokiPush = makeLokiPusher(LOKI_URL);

let promOk = 0, promFail = 0, lokiOk = 0, lokiFail = 0;

async function tickOnce() {
  simRef.tick += 1;
  const nowMs = Date.now();
  const state = computeTick({ tick: simRef.tick, nowMs, active });
  const samples = buildSamples(state, counters);
  const lines = buildLogLines(state);

  try {
    const r = await promPush(samples);
    promOk += 1;
    if (simRef.tick % 12 === 0) console.log(`[tick ${simRef.tick}] prom ${r.count} series ok`);
  } catch (e) {
    promFail += 1;
    console.error(`[tick ${simRef.tick}] prom push FAILED: ${e.message}`);
  }
  try {
    const r = await lokiPush(lines);
    lokiOk += 1;
    if (simRef.tick % 12 === 0) console.log(`[tick ${simRef.tick}] loki ${r.count} lines ok`);
  } catch (e) {
    lokiFail += 1;
    console.error(`[tick ${simRef.tick}] loki push FAILED: ${e.message}`);
  }
}

const control = await startControlServer({ port: PORT, active, simRef });
console.log(`OTT telemetry simulator`);
console.log(`  prometheus remote-write -> ${PROM_URL}`);
console.log(`  loki push               -> ${LOKI_URL}`);
console.log(`  control api             -> http://localhost:${PORT}`);
console.log(`  tick                    -> ${TICK_MS}ms`);
console.log(`Inject a scenario, e.g.:`);
console.log(`  curl -X POST localhost:${PORT}/scenarios/start -d "{\"name\":\"cdn-edge-degraded\"}"`);

await tickOnce();
setInterval(tickOnce, TICK_MS);

process.on("SIGINT", () => {
  console.log("\n[sim] shutting down");
  control.close();
  process.exit(0);
});
