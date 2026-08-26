// Log-line generation — the Loki evidence layer. Every scenario's metric
// signature has matching, grep-able log lines (the smoking gun the agent must
// cite). Fictional asset/channel ids only.

import { mulberry32 } from "./model.js";
import { WORLD } from "./model.js";

const CHANNELS = Array.from({ length: 80 }, (_, i) => `ch-${i + 1}`);
const FRESH_ASSETS = [
  "asset-8871", "asset-8884", "asset-8893", "asset-8901", "asset-8917",
];

function iso(nowMs) {
  return new Date(nowMs).toISOString().replace("T", " ").slice(0, 23) + "Z";
}

function sessionId(rnd) {
  return "s-" + Math.floor(rnd() * 0xffffff).toString(16).padStart(6, "0");
}

export function buildLogLines(state) {
  const rnd = mulberry32((state.tick * 7919) >>> 0);
  const lines = []; // {stream: {...}, line}
  const ts = iso(state.nowMs);

  const regionEdge = Object.fromEntries(
    Object.entries(state.edges).map(([edge, e]) => [e.region, edge])
  );

  // ---- player: error events (sampled but representative) ----
  for (const region of state.regions) {
    const rf = state.regionFactors[region.name] || {};
    for (const row of region.rows) {
      if (row.errors <= 0) continue;
      const slice = state.sliceFactors[`${region.name}|${row.platform}`];
      const types = Object.entries(row.errorsByType).sort((a, b) => b[1] - a[1]);
      const n = Math.min(3, 1 + Math.floor(row.errors / 400));
      for (let i = 0; i < n; i++) {
        const [type] = types[Math.floor(rnd() * types.length)] || ["segment_timeout"];
        const asset = type === "manifest_error" && state.globalFactors.freshAssetBurst
          ? FRESH_ASSETS[Math.floor(rnd() * FRESH_ASSETS.length)]
          : CHANNELS[Math.floor(rnd() * CHANNELS.length)];
        const detail =
          type === "segment_timeout" ? "segment timeout after 3 retries" :
          type === "manifest_error" ? "manifest fetch failed (404 upstream)" :
          type === "segment_404" ? "segment not found on edge" :
          type === "buffer_stall" ? "buffer underrun, playback stalled 8s" :
          type === "license_error" ? "license provider timeout after 5000ms" :
          "drm init failed: key server unreachable";
        lines.push({
          stream: { service: "player", env: "sim", region: region.name },
          line: `ts=${ts} level=error msg="playback session failed" session=${sessionId(rnd)} platform=${row.platform} region=${region.name} error=${type} asset=${asset} detail="${detail}" edge=${regionEdge[region.name] || "unknown"}`,
        });
      }
      // slice-specific ABR evidence
      if (slice && slice.logHint === "abr_downshift") {
        lines.push({
          stream: { service: "player", env: "sim", region: region.name },
          line: `ts=${ts} level=warn msg="abr downshift" session=${sessionId(rnd)} platform=${row.platform} region=${region.name} from_kbps=${state.rnd ? 3100 : 3100} to_kbps=460 detail="throughput 0.4 Mbps below floor"`,
        });
      }
    }
  }

  // ---- cdn: access lines + scenario evidence ----
  for (const [edge, e] of Object.entries(state.edges)) {
    const hit = rnd() > e.err5xxRatio * 20 ? 200 : 504;
    const ms = Math.round(e.latency * (hit === 200 ? jitter(rnd, 0.7, 1.1) : jitter(rnd, 1.6, 2.4)));
    const cache = hit === 200 ? (rnd() > 0.12 ? "HIT" : "MISS") : "MISS";
    const base = `ts=${ts} msg="seg fetch" edge=${edge} region=${e.region} asset=${CHANNELS[Math.floor(rnd() * CHANNELS.length)]} seg=${String(Math.floor(rnd() * 9999)).padStart(5, "0")} cache=${cache} status=${hit} ms=${ms}`;
    lines.push({
      stream: { service: "cdn", env: "sim", edge },
      line: hit === 504
        ? `${base} upstream_ms=${ms * 3} error=upstream_fetch_timeout`
        : (e.logHint ? `${base} upstream_ms=${Math.round(ms * 1.8)} slow_upstream=true` : base),
    });
  }

  // ---- origin: access + error lines ----
  for (const [origin, o] of Object.entries(state.origins)) {
    const asset = FRESH_ASSETS[Math.floor(rnd() * FRESH_ASSETS.length)];
    if (o.err5xxRatio > 0.05) {
      lines.push({
        stream: { service: "origin", env: "sim", origin },
        line: `ts=${ts} level=error msg="origin fetch failed" origin=${origin} asset=${asset} path=/vod/${asset}/seg-00${Math.floor(rnd() * 900) + 100}.ts status=503 ms=${Math.round(o.latency * 14)} error=dependency_timeout detail="packaging-db connect timeout after 2000ms"`,
      });
    } else if (rnd() > 0.4) {
      lines.push({
        stream: { service: "origin", env: "sim", origin },
        line: `ts=${ts} level=info msg="origin fetch" origin=${origin} asset=${asset} path=/vod/${asset}/manifest.mpd status=200 ms=${Math.round(o.latency * jitter(rnd, 0.8, 1.3))} cache=MISS`,
      });
    }
  }

  // ---- transcoders ----
  for (const [tname, tc] of Object.entries(state.transcoders)) {
    if (tc.queue > 20) {
      lines.push({
        stream: { service: "transcoder", env: "sim", transcoder: tname },
        line: `ts=${ts} level=warn msg="queue backlog" transcoder=${tname} depth=${Math.round(tc.queue)} lag_s=${Math.round(tc.lag)} asset=${FRESH_ASSETS[Math.floor(rnd() * FRESH_ASSETS.length)]}`,
      });
    }
    if (tc.dropsPerTick > 0) {
      lines.push({
        stream: { service: "transcoder", env: "sim", transcoder: tname },
        line: `ts=${ts} level=error msg="dropped frames" transcoder=${tname} frames=${tc.dropsPerTick * 40 + Math.floor(rnd() * 30)} asset=${FRESH_ASSETS[Math.floor(rnd() * FRESH_ASSETS.length)]} reason=overrun`,
      });
    }
  }

  // ---- ambient info noise (low volume, keeps streams alive) ----
  if (state.tick % 3 === 0) {
    const r = WORLD.regions[Math.floor(rnd() * WORLD.regions.length)];
    lines.push({
      stream: { service: "player", env: "sim", region: r.name },
      line: `ts=${ts} level=info msg="cohort healthy" region=${r.name} sessions_reported=ok error_rate_nominal=true`,
    });
  }

  return withSimTags(lines);
}

function jitter(rnd, lo, hi) {
  return lo + rnd() * (hi - lo);
}

// Loki stream tags applied to EVERY line this simulator pushes, so a judge
// (or the agent) can isolate the simulation with one label selector:
//   {job="incident-director", source="sim"}
export function withSimTags(lines) {
  return lines.map((l) => ({
    ...l,
    stream: { job: "incident-director", source: "sim", ...l.stream },
  }));
}
