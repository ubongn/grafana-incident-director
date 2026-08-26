// STEP 0 fail-fast check (M3): ONE-SHOT push + query verify against Grafana
// Cloud BEFORE any sim loop runs. Exits non-zero on any failure.
//
// Creds come from the staged grafana-cloud-creds.txt at the WORKSPACE root
// (never from .env — .env has been stale before). Run from sim/ or repo root:
//   node sim/verify-cloud.mjs
//
// Verifies, in order:
//   1. Prometheus remote-write push (snappy+protobuf via prometheus-remote-write,
//      the exact lib the sim uses) with basic auth PROM_USER:glc_ token
//   2. Prometheus instant query returns OUR series (retry — ingestion lag)
//   3. Loki JSON push -> 204 with basic auth LOKI_USER:glc_ token
//   4. Loki query_range returns OUR log line
import { pushTimeseries } from "prometheus-remote-write";
import { readFileSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const credsPath = resolve(dirname(fileURLToPath(import.meta.url)), "../../grafana-cloud-creds.txt");
const creds = {};
for (const line of readFileSync(credsPath, "utf8").replace(/^\uFEFF/, "").split(/\r?\n/)) {
  const m = line.match(/^([A-Z_]+)=(\S+)$/);
  if (m) creds[m[1]] = m[2];
}
const required = ["PROM_REMOTE_WRITE_URL", "PROM_QUERY_URL", "PROM_USER", "LOKI_PUSH_URL", "LOKI_USER", "GRAFANA_CLOUD_API_KEY"];
for (const k of required) if (!creds[k]) { console.error(`FAIL creds: missing ${k} in ${credsPath}`); process.exit(2); }

const RUN = String(Date.now());
const b64 = (u, p) => "Basic " + Buffer.from(`${u}:${p}`).toString("base64");
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let failed = 0;
const check = (name, ok, detail = "") => {
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail ? "  — " + detail : ""}`);
  if (!ok) failed += 1;
};

// --- 1. Prometheus remote-write push --------------------------------------
const METRIC = "hiclaw_m3_fix_verify";
let promPushStatus = "error";
try {
  const res = await pushTimeseries(
    [{ labels: { __name__: METRIC, job: "incident-director", source: "m3-fix", run: RUN }, samples: [{ value: 1 }] }],
    { url: creds.PROM_REMOTE_WRITE_URL, auth: { username: creds.PROM_USER, password: creds.GRAFANA_CLOUD_API_KEY } },
  );
  promPushStatus = `${res.status ?? "?"}`;
} catch (e) {
  promPushStatus = `throw: ${e.message}`;
}
check("prom push", promPushStatus === "200", `status ${promPushStatus}`);

// --- 2. Prometheus query returns our series --------------------------------
let promQuery = "never";
for (let i = 0; i < 10 && promQuery !== "ok"; i++) {
  if (i) await sleep(6000);
  const q = encodeURIComponent(`${METRIC}{run="${RUN}"}`);
  try {
    const r = await fetch(`${creds.PROM_QUERY_URL}/api/v1/query?query=${q}`, {
      headers: { Authorization: b64(creds.PROM_USER, creds.GRAFANA_CLOUD_API_KEY), Accept: "application/json" },
    });
    const j = await r.json().catch(() => ({}));
    if (r.status === 200 && j.status === "success" && (j.data?.result?.length ?? 0) > 0) promQuery = "ok";
    else promQuery = `HTTP ${r.status} ${JSON.stringify(j).slice(0, 160)}`;
  } catch (e) {
    promQuery = `throw: ${e.message}`;
  }
}
check("prom query round-trip", promQuery === "ok", promQuery);

// --- 3. Loki push ----------------------------------------------------------
const LINE = `m3-fix verify run=${RUN}`;
let lokiPush = "error";
try {
  const ns = String(Date.now() * 1e6);
  const r = await fetch(creds.LOKI_PUSH_URL, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: b64(creds.LOKI_USER, creds.GRAFANA_CLOUD_API_KEY) },
    body: JSON.stringify({ streams: [{ stream: { job: "incident-director" }, values: [[ns, LINE]] }] }),
  });
  lokiPush = r.status === 204 ? "ok" : `HTTP ${r.status} ${(await r.text()).slice(0, 160)}`;
} catch (e) {
  lokiPush = `throw: ${e.message}`;
}
check("loki push", lokiPush === "ok", lokiPush);

// --- 4. Loki query returns our line ----------------------------------------
let lokiQuery = "never";
const lokiBase = creds.LOKI_PUSH_URL.replace(/\/loki\/api\/v1\/push$/, "");
for (let i = 0; i < 8 && lokiQuery !== "ok"; i++) {
  if (i) await sleep(4000);
  const q = encodeURIComponent(`{job="incident-director"} |= "m3-fix verify"`);
  const start = new Date(Date.now() - 5 * 60_000).toISOString();
  try {
    const r = await fetch(`${lokiBase}/loki/api/v1/query_range?query=${q}&start=${start}&limit=5`, {
      headers: { Authorization: b64(creds.LOKI_USER, creds.GRAFANA_CLOUD_API_KEY), Accept: "application/json" },
    });
    const j = await r.json().catch(() => ({}));
    const lines = (j.data?.result ?? []).flatMap((s) => s.values.map(([, t]) => t));
    if (r.status === 200 && lines.some((t) => t.includes(RUN))) lokiQuery = "ok";
    else lokiQuery = `HTTP ${r.status} lines=${lines.length} ${JSON.stringify(j).slice(0, 120)}`;
  } catch (e) {
    lokiQuery = `throw: ${e.message}`;
  }
}
check("loki query round-trip", lokiQuery === "ok", lokiQuery);

console.log(failed ? `\nSTEP 0 FAILED (${failed} check(s)) — do NOT start the sim.` : "\nSTEP 0 OK — sim cleared to run.");
process.exit(failed ? 1 : 0);
