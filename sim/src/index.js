// OTT telemetry simulator — main loop.
// Every TICK_MS: compute one deterministic tick, remote-write Prometheus
// samples, push Loki log lines. Fault injection via control API (:8790).
//
// Deployments:
//   local (default): bare Prometheus :9090 / Loki :3100, no auth
//   Grafana Cloud:   set *_URL to the cloud endpoints + *_USERNAME and
//                    GRAFANA_CLOUD_API_KEY (basic auth) and SIM_CARDINALITY=cloud
//                    (see README "Grafana Cloud" section).

import { computeTick, buildSamples } from "./metrics.js";
import { buildLogLines, withSimTags } from "./logs.js";
import { makePromPusher, makeLokiPusher } from "./push.js";
import { startControlServer } from "./control.js";
import { takeEvidenceLines } from "./remediation.js";

const env = (k, d) => process.env[k] || d;
const PROM_URL = env("PROMETHEUS_REMOTE_WRITE_URL", "http://localhost:9090/api/v1/write");
const LOKI_URL = env("LOKI_PUSH_URL", "http://localhost:3100/loki/api/v1/push");
const PORT = parseInt(env("SIM_CONTROL_PORT", "8790"), 10);
const TICK_MS = parseInt(env("TICK_MS", "5000"), 10);

// --- Grafana Cloud auth (basic auth on both push endpoints) ---
// Convention: one cloud API key (glc_...) is the password; each endpoint has
// its own numeric instance-id username.
const cloudKey = env("GRAFANA_CLOUD_API_KEY", "");
const PROM_AUTH =
  env("PROM_USERNAME", "") && cloudKey
    ? { username: env("PROM_USERNAME"), password: cloudKey }
    : null;
const LOKI_AUTH =
  env("LOKI_USERNAME", "") && cloudKey
    ? { username: env("LOKI_USERNAME"), password: cloudKey }
    : null;

// --- cardinality mode ---
// full (default): every family at full label resolution (~400 active series)
// cloud: by-type error breakdown aggregated to region (~260 active series);
//        sized for the Grafana Cloud free tier (10k active series / 50GB logs)
const CARDINALITY = ["full", "cloud"].includes(env("SIM_CARDINALITY", "full"))
  ? env("SIM_CARDINALITY", "full")
  : "full";
const JOB_LABEL = env("SIM_JOB_LABEL", "hiclaw-sim");

const active = [];
const counters = Object.create(null);
const simRef = { tick: 0, startedAt: new Date().toISOString() };
const stats = {
  cardinality: CARDINALITY,
  jobLabel: JOB_LABEL,
  promUrl: PROM_URL,
  lokiUrl: LOKI_URL,
  lastSeriesCount: 0,
  promOk: 0,
  promFail: 0,
  lokiOk: 0,
  lokiFail: 0,
};

const promPush = makePromPusher(PROM_URL, PROM_AUTH);
const lokiPush = makeLokiPusher(LOKI_URL, LOKI_AUTH);

async function tickOnce() {
  simRef.tick += 1;
  const nowMs = Date.now();
  const state = computeTick({ tick: simRef.tick, nowMs, active });
  const samples = buildSamples(state, counters, {
    cardinality: CARDINALITY,
    jobLabel: JOB_LABEL,
  });
  const lines = [...buildLogLines(state), ...withSimTags(takeEvidenceLines())];
  stats.lastSeriesCount = samples.length;

  try {
    const r = await promPush(samples);
    stats.promOk += 1;
    if (simRef.tick % 12 === 0) console.log(`[tick ${simRef.tick}] prom ${r.count} series ok`);
  } catch (e) {
    stats.promFail += 1;
    console.error(`[tick ${simRef.tick}] prom push FAILED: ${e.message}`);
  }
  try {
    const r = await lokiPush(lines);
    stats.lokiOk += 1;
    if (simRef.tick % 12 === 0) console.log(`[tick ${simRef.tick}] loki ${r.count} lines ok`);
  } catch (e) {
    stats.lokiFail += 1;
    console.error(`[tick ${simRef.tick}] loki push FAILED: ${e.message}`);
  }
}

const control = await startControlServer({ port: PORT, active, simRef, stats });
console.log(`OTT telemetry simulator`);
console.log(`  prometheus remote-write -> ${PROM_URL}${PROM_AUTH ? " (basic auth)" : ""}`);
console.log(`  loki push               -> ${LOKI_URL}${LOKI_AUTH ? " (basic auth)" : ""}`);
console.log(`  control api             -> http://localhost:${PORT}`);
console.log(`  tick                    -> ${TICK_MS}ms`);
console.log(`  cardinality             -> ${CARDINALITY} (${stats.cardinality}) job=${JOB_LABEL}`);
console.log(`Inject a scenario, e.g.:`);
console.log(`  curl -X POST localhost:${PORT}/scenarios/start -d "{\"name\":\"cdn-edge-degraded\"}"`);

await tickOnce();
setInterval(tickOnce, TICK_MS);

process.on("SIGINT", () => {
  console.log("\n[sim] shutting down");
  console.log("[sim] final stats", JSON.stringify(stats));
  control.close();
  process.exit(0);
});
