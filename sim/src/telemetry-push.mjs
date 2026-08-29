// Agent-telemetry pusher: reads a JSON payload on stdin, remote-writes the
// samples to Prometheus via the same proven transport the sim uses
// (prometheus-remote-write package — do NOT hand-roll protobuf here; a
// previous hand-rolled probe returned 200 but never became queryable).
//
// Payload: { "samples": [ { "labels": { "__name__": "...", ...kv },
//                            "samples": [ { "value": 1.23 } ] } ] }
// Env: PROMETHEUS_REMOTE_WRITE_URL, PROM_USERNAME, GRAFANA_CLOUD_API_KEY
//      (same keys sim/src/index.js reads — agent .env already has them).
//
// Exit 0 + {"ok":true} on success; nonzero on any failure. Called at most
// once per incident arc, so process startup cost is irrelevant.

import { makePromPusher } from "./push.js";
import { readFileSync } from "node:fs";

const env = (k, d = "") => process.env[k] ?? d;

const url = env("PROMETHEUS_REMOTE_WRITE_URL", "http://localhost:9090/api/v1/write");
const user = env("PROM_USERNAME", "");
const key = env("GRAFANA_CLOUD_API_KEY", "");
const auth = user && key ? { username: user, password: key } : null;

let payload;
try {
  payload = JSON.parse(readFileSync(0, "utf8"));
} catch (e) {
  console.error("bad payload: " + e.message);
  process.exit(2);
}

const samples = Array.isArray(payload.samples) ? payload.samples : [];
if (!samples.length) {
  console.log(JSON.stringify({ ok: true, count: 0 }));
  process.exit(0);
}

try {
  const r = await makePromPusher(url, auth)(samples);
  console.log(JSON.stringify({ ok: true, count: r.count }));
} catch (e) {
  console.error("telemetry push failed: " + e.message);
  process.exit(1);
}
