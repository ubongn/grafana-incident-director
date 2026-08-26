// OTT world model: regions, platforms, CDN edges, origins, transcoders.
// Fictional platform "StreamFiction" — no real-world brand names anywhere.

export const WORLD = {
  seed: 0x57f1c7,
  regions: [
    { name: "eu-west", weight: 0.24 },
    { name: "eu-central", weight: 0.13 },
    { name: "us-east", weight: 0.22 },
    { name: "us-west", weight: 0.11 },
    { name: "ap-south", weight: 0.18 },
    { name: "ap-southeast", weight: 0.12 },
  ],
  platforms: [
    { name: "web", weight: 0.34, bitrate: 4800 },
    { name: "android", weight: 0.29, bitrate: 3100 },
    { name: "ios", weight: 0.21, bitrate: 3600 },
    { name: "tvos", weight: 0.10, bitrate: 6200 },
    { name: "firetv", weight: 0.06, bitrate: 4300 },
  ],
  edges: [
    // each edge primarily serves one region
    { name: "cdn-fra1", region: "eu-west", baseLatency: 96 },
    { name: "cdn-ams1", region: "eu-central", baseLatency: 88 },
    { name: "cdn-iad1", region: "us-east", baseLatency: 104 },
    { name: "cdn-sfo1", region: "us-west", baseLatency: 112 },
    { name: "cdn-bom1", region: "ap-south", baseLatency: 128 },
    { name: "cdn-sin1", region: "ap-southeast", baseLatency: 121 },
  ],
  origins: [
    { name: "origin-a", role: "primary", baseLatency: 34 },
    { name: "origin-b", role: "backup", baseLatency: 41 },
  ],
  transcoders: ["xc-01", "xc-02", "xc-03", "xc-04", "xc-05", "xc-06"],

  // healthy baselines
  baseSessions: 2_200_000,
  startupChurn: 0.011, // attempts per session per tick
  healthyErrorRate: 0.0035, // fraction of attempts that fail
  healthyErrorMix: {
    segment_timeout: 0.38,
    manifest_error: 0.18,
    buffer_stall: 0.18,
    segment_404: 0.14,
    license_error: 0.07,
    drm_init_failed: 0.05,
  },
  healthyRebufferFrac: 0.0015, // rebuffer seconds / watch seconds
  edgeReqPerSession: 1.25, // segments per session per tick (4s segments, 5s tick)
  edgeMissFrac: 0.08,
  healthyEdge5xx: 0.0002,
  healthyOrigin5xx: 0.0001,
};

export function mulberry32(seed) {
  let a = seed >>> 0;
  return function () {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

// Deterministic per-tick RNG: same tick index -> same noise, replayable.
export function tickRng(seed, tick, salt = 0) {
  return mulberry32((seed ^ (tick * 2654435761) ^ (salt * 40503)) >>> 0);
}

export function jitter(rnd, lo, hi) {
  return lo + rnd() * (hi - lo);
}

export function round2(x) {
  return Math.round(x * 100) / 100;
}
