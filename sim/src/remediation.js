// Remediation control — the closed-loop actuator side of the sim.
//
// POST /remediate {"action": "...", ...params} neutralizes the matching
// ACTIVE scenario: its fault intensity k decays exponentially (tau ~25s) so
// telemetry visibly recovers over the following minutes. A remediation that
// doesn't match any active incident is rejected (409) — a false action can
// never "fix" a world that isn't broken.
//
// Every applied remediation also emits Loki evidence lines (service=control).

const TAU_SECONDS = 25;

// action -> { params check + which scenario it neutralizes }
export const REMEDIATIONS = {
  drain_cdn_edge: {
    scenario: "cdn-edge-degraded",
    check: (params, sc) => (!params.edge || sc.params.edge === params.edge
      ? { ok: true }
      : { ok: false, status: 409, error: `wrong edge: incident is on ${sc.params.edge}, tried ${params.edge}` }),
  },
  failover_origin: {
    scenario: "origin-5xx",
    check: (params, sc) => (!params.to_origin || params.to_origin === "origin-b"
      ? { ok: true }
      : { ok: false, status: 409, error: `invalid failover target: ${params.to_origin}` }),
  },
  switch_license_endpoint: {
    scenario: "drm-license-outage",
    check: () => ({ ok: true }),
  },
  throttle_ingest: {
    scenario: "transcoder-backlog",
    check: () => ({ ok: true }),
  },
  tighten_abr_floor: {
    scenario: "regional-isp-degradation",
    check: (params, sc) => {
      const p = sc.params;
      const regionOk = !params.region || params.region === p.region;
      const platformOk = !params.platform || params.platform === p.platform;
      return regionOk && platformOk
        ? { ok: true }
        : { ok: false, status: 409, error: `cohort mismatch: incident is ${p.region}/${p.platform}, tried ${params.region}/${params.platform}` };
    },
  },
};

let evidenceQueue = [];

export function takeEvidenceLines() {
  const out = evidenceQueue;
  evidenceQueue = [];
  return out;
}

export function applyRemediation(payload, active, nowMs = Date.now()) {
  const { action, ...params } = payload || {};
  const spec = REMEDIATIONS[action];
  if (!spec) {
    return { status: 400, body: { error: `unknown action: ${action}`, available: Object.keys(REMEDIATIONS) } };
  }
  const targets = active.filter((s) => s.name === spec.scenario);
  if (targets.length === 0) {
    return {
      status: 409,
      body: { error: `no active incident matches ${action}`, active: active.map((s) => s.name) },
    };
  }
  const neutralized = [];
  for (const sc of targets) {
    const verdict = spec.check(params, sc);
    if (!verdict.ok) return { status: verdict.status, body: { error: verdict.error } };
    sc.suppress(nowMs, TAU_SECONDS);
    neutralized.push(sc.id);
  }
  const id = `rem-${String(evidenceSeq++).padStart(3, "0")}`;
  const ts = new Date(nowMs).toISOString().replace("T", " ").slice(0, 23) + "Z";
  evidenceQueue.push({
    stream: { service: "control", env: "sim" },
    line: `ts=${ts} level=info msg="remediation applied" id=${id} action=${action} targets=${neutralized.join(",")} params=${JSON.stringify(params)} tau_s=${TAU_SECONDS}`,
  });
  return {
    status: 200,
    body: { ok: true, id, action, params, neutralized: neutralized, recovery_tau_s: TAU_SECONDS },
  };
}

let evidenceSeq = 1;
