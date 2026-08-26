// Offline tests for the cloud-mode telemetry changes (no network).
// Run: npm test   (node --test, built into Node >= 20)

import test from "node:test";
import assert from "node:assert/strict";

import { computeTick, buildSamples } from "../src/metrics.js";
import { buildLogLines, withSimTags } from "../src/logs.js";
import { basicAuthHeader } from "../src/push.js";

function oneTick() {
  return computeTick({ tick: 3, nowMs: Date.parse("2026-08-26T12:00:00Z"), active: [] });
}

test("full mode: errors_by_type is per region+platform slice", () => {
  const state = oneTick();
  const counters = Object.create(null);
  const samples = buildSamples(state, counters, { cardinality: "full" });
  const byType = samples.filter((s) => s.labels.__name__ === "ott_playback_errors_by_type_total");
  assert.ok(byType.length > 6 * 5, "expected >30 by-type series in full mode");
  for (const s of byType) {
    assert.ok(s.labels.region && s.labels.platform, "slice labels present");
  }
});

test("cloud mode: errors_by_type aggregated to region (no platform label)", () => {
  const state = oneTick();
  const counters = Object.create(null);
  const samples = buildSamples(state, counters, { cardinality: "cloud" });
  const byType = samples.filter((s) => s.labels.__name__ === "ott_playback_errors_by_type_total");
  for (const s of byType) {
    assert.equal(s.labels.platform, undefined, "platform dimension dropped");
    assert.ok(s.labels.region, "region kept");
  }
  // 6 regions x healthy error-mix types (~6) — bounded, no slice fan-out
  assert.ok(byType.length <= 6 * 10, `cloud by-type bounded (${byType.length})`);
});

test("cloud mode cardinality stays well under the 5k target", () => {
  const state = oneTick();
  const counters = Object.create(null);
  const samples = buildSamples(state, counters, { cardinality: "cloud" });
  assert.ok(samples.length < 5000, `series per tick = ${samples.length}`);
  // and materially slimmer than full mode
  const full = buildSamples(computeTick({ tick: 3, nowMs: Date.now(), active: [] }), Object.create(null), {
    cardinality: "full",
  });
  assert.ok(samples.length < full.length, `cloud ${samples.length} < full ${full.length}`);
});

test("cloud mode keeps every scenario-critical family queryable", () => {
  const state = oneTick();
  const counters = Object.create(null);
  const samples = buildSamples(state, counters, { cardinality: "cloud" });
  const names = new Set(samples.map((s) => s.labels.__name__));
  for (const n of [
    "ott_sessions_active",
    "ott_playback_attempts_total",
    "ott_playback_errors_total",
    "ott_playback_errors_by_type_total",
    "ott_watch_seconds_total",
    "ott_rebuffer_seconds_total",
    "ott_delivered_bitrate_kbps",
    "ott_cdn_edge_requests_total",
    "ott_cdn_edge_errors_total",
    "ott_cdn_edge_latency_ms",
    "ott_origin_requests_total",
    "ott_origin_errors_total",
    "ott_origin_latency_ms",
    "ott_transcoder_queue_depth",
  ]) {
    assert.ok(names.has(n), `${n} present in cloud mode`);
  }
});

test("job label stamps every series when requested", () => {
  const state = oneTick();
  const counters = Object.create(null);
  const samples = buildSamples(state, counters, { cardinality: "cloud", jobLabel: "hiclaw-sim" });
  assert.ok(samples.length > 0);
  for (const s of samples) assert.equal(s.labels.job, "hiclaw-sim");
  const bare = buildSamples(state, Object.create(null), {});
  for (const s of bare) assert.equal(s.labels.job, undefined);
});

test("counters stay monotonic across ticks in cloud mode", () => {
  const counters = Object.create(null);
  let prev = 0;
  for (let tick = 1; tick <= 3; tick++) {
    const state = computeTick({ tick, nowMs: tick * 5000, active: [] });
    const samples = buildSamples(state, counters, { cardinality: "cloud" });
    const errs = samples
      .filter((s) => s.labels.__name__ === "ott_playback_errors_total" && s.labels.region === "eu-west" && s.labels.platform === "web")
      .map((s) => s.samples[0].value);
    assert.equal(errs.length, 1);
    assert.ok(errs[0] >= prev, `cumulative counter grows: ${errs[0]} >= ${prev}`);
    prev = errs[0];
  }
});

test("every log line carries job=incident-director, source=sim", () => {
  const state = oneTick();
  const lines = buildLogLines(state);
  assert.ok(lines.length > 0);
  for (const l of lines) {
    assert.equal(l.stream.job, "incident-director");
    assert.equal(l.stream.source, "sim");
    assert.ok(l.stream.service, "service label preserved");
  }
});

test("withSimTags stamps evidence lines without clobbering their labels", () => {
  const out = withSimTags([{ stream: { service: "control", env: "sim" }, line: "x" }]);
  assert.deepEqual(out[0].stream, { job: "incident-director", source: "sim", service: "control", env: "sim" });
});

test("basic auth header is well-formed", () => {
  const h = basicAuthHeader("3541552", "glc_secret");
  assert.equal(h, "Basic " + Buffer.from("3541552:glc_secret").toString("base64"));
  assert.ok(h.startsWith("Basic "));
});
