// Computes one tick of OTT telemetry: healthy baselines, then scenario
// mutation, then the Prometheus sample set. Counters are cumulative so the
// agent can use rate() over any window; gauges are instantaneous.

import { WORLD, tickRng, jitter, round2 } from "./model.js";

export function computeTick({ tick, nowMs, active }) {
  const rnd = tickRng(WORLD.seed, tick, 7);

  const state = {
    tick,
    nowMs,
    rnd,
    regions: [],
    regionNames: WORLD.regions.map((r) => r.name),
    regionFactors: {},
    sliceFactors: {},
    globalFactors: { licenseErrorShare: 0, manifestErrorMultiplier: 1 },
    edges: {},
    origins: {},
    transcoders: {},
    transcoderNames: WORLD.transcoders,
  };

  for (const e of WORLD.edges) {
    state.edges[e.name] = {
      region: e.region,
      latency: e.baseLatency * jitter(rnd, 0.9, 1.15),
      err5xxRatio: WORLD.healthyEdge5xx,
    };
  }
  for (const o of WORLD.origins) {
    state.origins[o.name] = {
      role: o.role,
      latency: o.baseLatency * jitter(rnd, 0.85, 1.3),
      err5xxRatio: WORLD.healthyOrigin5xx,
    };
  }
  for (const t of WORLD.transcoders) {
    state.transcoders[t] = {
      queue: jitter(rnd, 2, 9),
      lag: jitter(rnd, 1, 6),
      dropsPerTick: rnd() > 0.97 ? 1 : 0,
    };
  }

  // ---- scenarios mutate state BEFORE derived rows are computed ----
  for (const sc of active) sc.def.apply(state, sc, nowMs);

  // ---- sessions per region/platform ----
  // diurnal-ish slow sine (10% amplitude, 6h period) for session realism
  const hourPhase = (nowMs / 1000 / 3600) % 6;
  const diurnal = 1 + 0.1 * Math.sin((2 * Math.PI * hourPhase) / 6);
  const sessionMult =
    (state.globalFactors.sessionMultiplier || 1) * diurnal;
  const totalSessions = WORLD.baseSessions * sessionMult;

  for (const region of WORLD.regions) {
    const rf = state.regionFactors[region.name] || {};
    const rows = WORLD.platforms.map((platform) => {
      let sessions = totalSessions * region.weight * platform.weight;
      let errorMult = rf.errorMultiplier || 1;
      let rebufferMult = 1;

      const slice = state.sliceFactors[`${region.name}|${platform.name}`];
      if (slice) {
        errorMult *= slice.errorMultiplier || 1;
        rebufferMult = slice.rebufferMultiplier || 1;
      }

      const attempts = sessions * WORLD.startupChurn * jitter(rnd, 0.97, 1.03);

      // error composition: healthy mix, regional bias, slice bias, global overrides
      let mix = { ...WORLD.healthyErrorMix };
      const applyBias = (bias) => {
        if (!bias) return;
        const rest = 1 - Object.values(bias).reduce((a, b) => a + b, 0);
        for (const k of Object.keys(mix)) mix[k] *= Math.max(0.02, rest);
        Object.assign(mix, bias);
      };
      applyBias(rf.errorMixBias);
      const sliceKey = `${region.name}|${platform.name}`;
      if (state.sliceFactors[sliceKey]) applyBias(state.sliceFactors[sliceKey].errorMixBias);

      // global manifest multiplier (transcoder backlog)
      if (state.globalFactors.manifestErrorMultiplier > 1) {
        mix.manifest_error = (mix.manifest_error || 0) * state.globalFactors.manifestErrorMultiplier;
      }

      let errors = attempts * WORLD.healthyErrorRate * errorMult * jitter(rnd, 0.9, 1.1);
      // global license outage replaces part of the error budget with license errors
      const licShare = state.globalFactors.licenseErrorShare || 0;
      if (licShare > 0) {
        errors = attempts * (WORLD.healthyErrorRate * errorMult + licShare);
        mix.license_error = licShare / (WORLD.healthyErrorRate * errorMult + licShare);
        for (const k of Object.keys(mix)) if (k !== "license_error") mix[k] *= 1 - mix.license_error;
      }

      const watchSeconds = sessions * 5 * 0.996;
      const rebufferSeconds =
        watchSeconds * WORLD.healthyRebufferFrac * rebufferMult * jitter(rnd, 0.85, 1.15);

      const errorsByType = {};
      let acc = 0;
      for (const [type, w] of Object.entries(mix)) {
        const c = Math.max(0, Math.round(errors * w));
        errorsByType[type] = c;
        acc += c;
      }

      return {
        region: region.name,
        platform: platform.name,
        sessions: Math.round(sessions),
        attempts,
        errors: acc,
        errorsByType,
        watchSeconds,
        rebufferSeconds,
        bitrate: platform.bitrate * jitter(rnd, 0.93, 1.07),
      };
    });
    state.regions.push({ name: region.name, rows });
  }

  return state;
}

export function buildSamples(state, counters, opts = {}) {
  const cardinality = opts.cardinality || "full"; // "full" | "cloud" (see README)
  const jobLabel = opts.jobLabel || ""; // e.g. "hiclaw-sim": stamps every series
  const samples = [];

  const push = (name, labels, value) =>
    samples.push({
      labels: {
        __name__: name,
        ...(jobLabel ? { job: jobLabel } : {}),
        ...labels,
      },
      samples: [{ value: Math.max(0, typeof value === "number" ? round2(value) : value) }],
    });

  // counters carry cumulative totals
  const cum = (key, labels) => {
    const id = key + JSON.stringify(labels);
    if (counters[id] === undefined) counters[id] = 0;
    return {
      add(n) {
        counters[id] += n;
        return counters[id];
      },
    };
  };

  for (const region of state.regions) {
    for (const row of region.rows) {
      const labels = { region: row.region, platform: row.platform };
      push("ott_sessions_active", labels, row.sessions);
      cum("attempts", labels).add(row.attempts);
      push("ott_playback_attempts_total", labels, counters["attempts" + JSON.stringify(labels)]);
      cum("errors", labels).add(row.errors);
      push("ott_playback_errors_total", labels, counters["errors" + JSON.stringify(labels)]);
      if (cardinality !== "cloud") {
        for (const [type, n] of Object.entries(row.errorsByType)) {
          const l2 = { ...labels, error_type: type };
          cum("errors_t", l2).add(n);
          push("ott_playback_errors_by_type_total", l2, counters["errors_t" + JSON.stringify(l2)]);
        }
      }
      cum("watch", labels).add(row.watchSeconds);
      push("ott_watch_seconds_total", labels, counters["watch" + JSON.stringify(labels)]);
      cum("rebuffer", labels).add(row.rebufferSeconds);
      push("ott_rebuffer_seconds_total", labels, counters["rebuffer" + JSON.stringify(labels)]);
      push("ott_delivered_bitrate_kbps", labels, row.bitrate);
    }
    if (cardinality === "cloud") {
      // SIM_CARDINALITY=cloud: drop the platform dimension from the by-type
      // error breakdown — 30 slices x ~6 types (~180 series) collapses to
      // 6 regions x ~6 types (~36 series). Every other family is untouched,
      // so error composition evidence (the diagnose phase's key signal)
      // stays queryable, just one label narrower. Full arc stays far below
      // the Grafana Cloud free tier's 10k active-series cap.
      const byType = {};
      for (const row of region.rows)
        for (const [type, n] of Object.entries(row.errorsByType))
          byType[type] = (byType[type] || 0) + n;
      for (const [type, n] of Object.entries(byType)) {
        const l2 = { region: region.name, error_type: type };
        cum("errors_t", l2).add(n);
        push("ott_playback_errors_by_type_total", l2, counters["errors_t" + JSON.stringify(l2)]);
      }
    }
  }

  const latencyAddFrac = state.globalFactors.latencyAddFrac || 0;
  for (const [edge, e] of Object.entries(state.edges)) {
    const labels = { edge, region: e.region };
    const reqs = state.regions
      .find((r) => r.name === e.region)
      .rows.reduce((a, r) => a + r.sessions * WORLD.edgeReqPerSession, 0);
    cum("edge_req", labels).add(reqs);
    push("ott_cdn_edge_requests_total", labels, counters["edge_req" + JSON.stringify(labels)]);
    const errs = reqs * e.err5xxRatio;
    cum("edge_err", labels).add(errs);
    push("ott_cdn_edge_errors_total", { ...labels, code: "504" }, counters["edge_err" + JSON.stringify(labels)]);
    push("ott_cdn_edge_latency_ms", labels, e.latency * (1 + latencyAddFrac));
  }

  for (const [origin, o] of Object.entries(state.origins)) {
    const labels = { origin, service: o.role };
    let reqs = o.role === "backup" ? 5 : 0;
    for (const region of state.regions)
      reqs += region.rows.reduce((a, r) => a + r.sessions, 0) * WORLD.edgeReqPerSession * WORLD.edgeMissFrac / WORLD.regions.length;
    cum("origin_req", labels).add(reqs);
    push("ott_origin_requests_total", labels, counters["origin_req" + JSON.stringify(labels)]);
    const errs = reqs * o.err5xxRatio;
    cum("origin_err", labels).add(errs);
    push("ott_origin_errors_total", { ...labels, code: o.logHint === "dependency_timeout" ? "503" : "500" }, counters["origin_err" + JSON.stringify(labels)]);
    push("ott_origin_latency_ms", labels, o.latency * (1 + latencyAddFrac));
  }

  for (const [tname, tc] of Object.entries(state.transcoders)) {
    const labels = { transcoder: tname };
    push("ott_transcoder_queue_depth", labels, tc.queue);
    push("ott_transcoder_lag_seconds", labels, tc.lag);
    cum("xc_drop", labels).add(tc.dropsPerTick);
    push("ott_transcoder_dropped_frames_total", labels, counters["xc_drop" + JSON.stringify(labels)]);
  }

  return samples;
}
