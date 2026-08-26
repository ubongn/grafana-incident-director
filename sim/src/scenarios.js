// Deterministic fault-injection scenarios. Each scenario mutates the healthy
// per-tick telemetry state with a time profile (ramp -> hold) so the Incident
// Director agent sees believable incident dynamics and matching log evidence.
//
// No-action trap: "traffic-spike" raises load while all quality ratios stay
// inside budget — the agent must refuse to remediate.

let nextId = 1;

export class ScenarioInstance {
  constructor(name, def, startedMs, params = {}) {
    this.id = `sc-${String(nextId++).padStart(3, "0")}`;
    this.name = name;
    this.def = def;
    this.params = { ...(def.defaults || {}), ...params };
    this.startedMs = startedMs;
    this.stoppedMs = null;
  }

  ageSeconds(nowMs) {
    return (nowMs - this.startedMs) / 1000;
  }
}

// profile: 0..1 intensity, ramps up over `rampSeconds`, holds until stopped.
function profile(ageSec, rampSeconds) {
  if (ageSec <= 0) return 0;
  return Math.min(1, ageSec / rampSeconds);
}

export const SCENARIOS = {
  "cdn-edge-degraded": {
    title: "CDN edge degraded (upstream fetch timeouts)",
    doc: "One CDN edge's upstream fetches time out; latency spikes and segment errors concentrate in the region it serves. Correct response: drain the edge / shift traffic, then verify recovery.",
    defaults: { edge: "cdn-fra1" },
    apply(state, sc, nowMs) {
      const k = profile(sc.ageSeconds(nowMs), 60);
      const edge = sc.params.edge;
      const region = state.edges[edge]?.region;
      if (!region) return;
      state.edges[edge].latency = 1400 + 1200 * k * state.rnd();
      state.edges[edge].err5xxRatio = 0.05 * k;
      state.edges[edge].logHint = "upstream_fetch_timeout";
      state.regionFactors[region] = state.regionFactors[region] || {};
      const rf = state.regionFactors[region];
      rf.errorMultiplier = (rf.errorMultiplier || 1) * (1 + 7 * k);
      rf.errorMixBias = { segment_timeout: 0.7, segment_404: 0.2 };
      rf.cdnLogHint = { edge, kind: "upstream_fetch_timeout" };
    },
  },

  "origin-5xx": {
    title: "Origin 5xx (dependency timeout)",
    doc: "Primary origin starts returning 503s from a packaging dependency. ALL regions degrade (origin is behind every edge) while CDN edge health stays normal — the discriminator. Correct response: fail over to origin-b, then verify.",
    defaults: { origin: "origin-a" },
    apply(state, sc, nowMs) {
      const k = profile(sc.ageSeconds(nowMs), 45);
      const origin = sc.params.origin;
      state.origins[origin].err5xxRatio = 0.45 * k;
      state.origins[origin].latency = state.origins[origin].latency * (1 + 3 * k);
      state.origins[origin].logHint = "dependency_timeout";
      for (const regionName of state.regionNames) {
        const rf = (state.regionFactors[regionName] = state.regionFactors[regionName] || {});
        rf.errorMultiplier = (rf.errorMultiplier || 1) * (1 + 5 * k);
        rf.errorMixBias = { manifest_error: 0.6, segment_timeout: 0.3 };
        rf.originLogHint = { origin, kind: "dependency_timeout" };
      }
    },
  },

  "drm-license-outage": {
    title: "DRM license provider outage",
    doc: "External license provider fails: license errors spike uniformly across ALL regions and platforms while CDN, origin and packaging stay pristine. Correct response: switch to the secondary license endpoint — not a CDN/origin action.",
    defaults: {},
    apply(state, sc, nowMs) {
      const k = profile(sc.ageSeconds(nowMs), 40);
      state.globalFactors.licenseErrorShare = 0.11 * k; // of ALL attempts
    },
  },

  "transcoder-backlog": {
    title: "Transcoder backlog (ingest surge)",
    doc: "Ingest surge floods packaging: queue depth and lag climb, frames drop, newly ingested assets fail manifest fetches. Correct response: route ingest to the burst pool / throttle low-priority ingest, then verify lag recovery.",
    defaults: {},
    apply(state, sc, nowMs) {
      const k = profile(sc.ageSeconds(nowMs), 90);
      for (const t of state.transcoderNames) {
        state.transcoders[t].queue = 30 + 150 * k * (0.7 + 0.6 * state.rnd());
        state.transcoders[t].lag = 20 + 130 * k;
        state.transcoders[t].dropsPerTick = Math.round(3 * k);
        state.transcoders[t].logHint = "ingest_backlog";
      }
      state.globalFactors.manifestErrorMultiplier = 1 + 2.5 * k;
      state.globalFactors.freshAssetBurst = k > 0.3; // manifest errors cite recent asset ids
    },
  },

  "regional-isp-degradation": {
    title: "Regional ISP degradation (client network)",
    doc: "One ISP path into one region degrades: rebuffering and segment timeouts hit only that region's cohort while CDN edges and origins stay healthy. Correct response: tighten ABR floor for the affected cohort and file ISP escalation — do not touch CDN/origin.",
    defaults: { region: "us-east", platform: "android" },
    apply(state, sc, nowMs) {
      const k = profile(sc.ageSeconds(nowMs), 50);
      const key = `${sc.params.region}|${sc.params.platform}`;
      state.sliceFactors[key] = {
        rebufferMultiplier: 1 + 14 * k,
        errorMultiplier: 1 + 4 * k,
        errorMixBias: { segment_timeout: 0.75 },
        logHint: "abr_downshift",
      };
    },
  },

  "traffic-spike": {
    title: "Benign traffic spike (NO-ACTION trap)",
    doc: "A live event drives sessions up ~60%. Error rate, rebuffer, origin and CDN health all stay within budget — this is load, not an incident. Correct response: explicitly DO NOTHING (log a note, no remediation).",
    defaults: {},
    apply(state, sc, nowMs) {
      const k = profile(sc.ageSeconds(nowMs), 90);
      state.globalFactors.sessionMultiplier = 1 + 0.6 * k;
      state.globalFactors.latencyAddFrac = 0.08 * k; // mild queueing delay everywhere
      state.globalFactors.benign = true;
    },
  },
};

export function listScenarios() {
  return Object.entries(SCENARIOS).map(([name, s]) => ({
    name,
    title: s.title,
    doc: s.doc,
    defaults: s.defaults || {},
  }));
}
