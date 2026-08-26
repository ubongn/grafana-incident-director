// Post-run cloud check: is the sim's series + its Loki logs queryable?
// Usage: node deploy/cloud-check.mjs [promql] [logql]
import { readFileSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const creds = {};
for (const line of readFileSync(resolve(dirname(fileURLToPath(import.meta.url)), "../../grafana-cloud-creds.txt"), "utf8").replace(/^\uFEFF/, "").split(/\r?\n/)) {
  const m = line.match(/^([A-Z_]+)=(\S+)$/);
  if (m) creds[m[1]] = m[2];
}
const b64 = (u, p) => "Basic " + Buffer.from(`${u}:${p}`).toString("base64");

const promql = process.argv[2] ?? 'ott_sessions_active{job="hiclaw-sim"}';
const r = await fetch(`${creds.PROM_QUERY_URL}/api/v1/query?query=${encodeURIComponent(promql)}`, {
  headers: { Authorization: b64(creds.PROM_USER, creds.GRAFANA_CLOUD_API_KEY) },
});
const j = await r.json();
const series = j.data?.result ?? [];
console.log(`PROM ${promql} -> HTTP ${r.status} ${j.status} | ${series.length} series`);
if (series[0]) console.log("  e.g.", JSON.stringify(series[0].metric), "=", series[0].value?.[1]);

const logql = process.argv[3] ?? '{job="incident-director", source="sim"}';
const lokiBase = creds.LOKI_PUSH_URL.replace(/\/loki\/api\/v1\/push$/, "");
const start = new Date(Date.now() - 10 * 60_000).toISOString();
const lr = await fetch(`${lokiBase}/loki/api/v1/query_range?query=${encodeURIComponent(logql)}&start=${start}&limit=3`, {
  headers: { Authorization: b64(creds.LOKI_USER, creds.GRAFANA_CLOUD_API_KEY) },
});
const lj = await lr.json().catch(() => ({}));
console.log(`LOKI ${logql} -> HTTP ${lr.status} ${lj.status ?? "?"} | streams ${lj.data?.result?.length ?? 0}`);
for (const s of (lj.data?.result ?? []).slice(0, 2))
  console.log("  ", JSON.stringify(s.stream), s.values.slice(-1).flat()[1]?.slice(0, 90));
