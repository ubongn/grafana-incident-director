"""Telemetry self-test: emit one clearly-labeled synthetic arc through the
REAL transport (Node remote-write + Loki JSON push), then read the samples
back from hosted Prometheus to prove they are queryable.

This exists because a previous hand-rolled remote-write probe returned
HTTP 200 while the series never became queryable — "push says ok" is not
verification. Run before recording (docs/demo-day.md preflight) and after
any transport change:

    cd agent && .venv\\Scripts\\python scripts\\telemetry_selftest.py

Exit 0 iff push + readback both succeed.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from incident_director import telemetry
from incident_director.config import load_settings
from incident_director.gate import GateDecision
from incident_director.models.phases import PhaseRecord
from incident_director.runbook.arc import ArcResult
from incident_director.telemetry import emit_run, run_samples

import os


def main() -> int:
    settings = load_settings()
    model = settings.gemini_model

    r = ArcResult(run_id=f"selftest-{time.strftime('%Y%m%d-%H%M%S')}", trigger_type="selftest", trigger_text="telemetry self-test")
    r.phases = [
        PhaseRecord(phase="detect", ok=True, seconds=0.1, tool_calls=["alerting_manage_rules"], usage={"prompt": 10, "candidates": 2, "thoughts": 0, "total": 12}),
        PhaseRecord(phase="report", ok=True, seconds=0.1, tool_calls=["create_annotation"], usage={"prompt": 10, "candidates": 2, "thoughts": 0, "total": 12}),
    ]
    r.gate = GateDecision(approved=False, decided_by="selftest", reason="synthetic", ts=time.strftime("%Y-%m-%dT%H:%M:%SZ"))
    r.outcome = "selftest"
    r.t_start, r.t_proposal, r.t_end = time.time() - 1, time.time() - 0.5, time.time()
    meta = {"scenario": "telemetry-selftest", "inject_to_firing_s": 0.1, "alert_rule_uid": "selftest"}

    print("pushing synthetic self-test arc through the real transport ...")
    emit_run(r, meta, settings, verbose=True)

    # read back from hosted Prometheus (query URL + basic auth from env)
    qurl = os.environ.get("PROM_QUERY_URL", "").rstrip("/")
    if not qurl:
        # derive from the remote-write URL: Grafana Cloud uses
        # .../api/prom/push (write) and .../api/prom (query base)
        rw = os.environ.get("PROMETHEUS_REMOTE_WRITE_URL", "").rstrip("/")
        for suffix in ("/api/v1/write", "/push"):
            if rw.endswith(suffix):
                rw = rw[: -len(suffix)]
                break
        qurl = rw.rstrip("/")
    user = os.environ.get("PROM_USER") or os.environ.get("PROM_USERNAME", "")
    key = os.environ.get("GRAFANA_CLOUD_API_KEY", "")
    if not qurl:
        print("SKIP readback: PROM_QUERY_URL not set")
        return 0
    import httpx

    resp = httpx.get(
        f"{qurl}/api/v1/query",
        params={"query": 'incident_director_phase_seconds{job="incident-director",phase="detect"}'},
        auth=(user, key) if user and key else None,
        timeout=20,
    )
    try:
        data = resp.json()
    except ValueError:
        print(f"FAIL: non-JSON readback (HTTP {resp.status_code}): {resp.text[:200]}")
        return 1
    n = len(data.get("data", {}).get("result", []))
    print(f"readback: HTTP {resp.status_code}, series={n}")
    if resp.status_code != 200 or n == 0:
        print("FAIL: pushed but not queryable — transport regression")
        return 1
    print("OK: self-test series queryable in hosted Prometheus")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
