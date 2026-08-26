"""Provision the OTT dashboard + SLO alert rules into Grafana Cloud via API.

Reads the same artifacts the local stack file-provisions
(deploy/grafana/dashboards/ott-streaming-ops.json and
deploy/grafana/provisioning/alerting/ott-core-slo.yml), rewrites datasource
uids to the stack's hosted datasources, and pushes them through the Grafana
HTTP API with a service-account token (Admin). Idempotent: re-running
overwrites the dashboard and replaces rules with matching uids.

Creds come from the staged grafana-cloud-creds.txt at the workspace root
(never committed) or from env:
  GRAFANA_URL, GRAFANA_SERVICE_ACCOUNT_TOKEN

Usage:
  python deploy/provision_cloud.py [path/to/grafana-cloud-creds.txt]
"""
from __future__ import annotations

import copy
import json
import re
import sys
from pathlib import Path

import httpx
import yaml

REPO = Path(__file__).resolve().parents[1]

LOCAL_PROM_UID = "prom-ott"  # uid used by the local docker/file provisioning


def load_creds(arg: str | None) -> tuple[str, str]:
    if arg:
        creds = {}
        for line in Path(arg).read_text().splitlines():
            m = re.match(r"^(GRAFANA_URL|GRAFANA_SA_TOKEN)=(\S+)$", line.strip())
            if m:
                creds[m.group(1)] = m.group(2)
        return creds["GRAFANA_URL"].rstrip("/"), creds["GRAFANA_SA_TOKEN"]
    import os
    url = os.environ.get("GRAFANA_URL", "").rstrip("/")
    tok = os.environ.get("GRAFANA_SERVICE_ACCOUNT_TOKEN", "")
    if url and tok:
        return url, tok
    raise SystemExit("no creds: pass the creds file path or set GRAFANA_URL + GRAFANA_SERVICE_ACCOUNT_TOKEN")


def main() -> int:
    url, token = load_creds(sys.argv[1] if len(sys.argv) > 1 else None)
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    with httpx.Client(timeout=30.0, headers=headers, base_url=url) as c:
        # --- resolve hosted datasource uids ---
        ds = c.get("/api/datasources")
        ds.raise_for_status()
        prom = next((d for d in ds.json() if d["type"] == "prometheus" and d.get("isDefault")), None) \
            or next(d for d in ds.json() if d["type"] == "prometheus")
        loki = next((d for d in ds.json() if d["type"] == "loki" and "logs" in d["uid"]), None) \
            or next(d for d in ds.json() if d["type"] == "loki")
        print(f"prom datasource: {prom['uid']} ({prom['name']})")
        print(f"loki datasource: {loki['uid']} ({loki['name']})")

        # --- folder ---
        folders = c.get("/api/folders").json()
        folder = next((f for f in folders if f["title"] == "OTT Incidents"), None)
        if folder is None:
            r = c.post("/api/folders", json={"title": "OTT Incidents"})
            r.raise_for_status()
            folder = r.json()
            print(f"created folder OTT Incidents ({folder['uid']})")
        else:
            print(f"folder OTT Incidents exists ({folder['uid']})")

        # --- dashboard (rewrite datasource refs to the hosted prom) ---
        dash_path = REPO / "deploy/grafana/dashboards/ott-streaming-ops.json"
        dash = json.loads(dash_path.read_text().replace(LOCAL_PROM_UID, prom["uid"]))
        r = c.post(
            "/api/dashboards/db",
            json={"dashboard": dash, "folderUid": folder["uid"], "overwrite": True,
                  "message": "provisioned by provision_cloud.py (M3)"},
        )
        r.raise_for_status()
        print(f"dashboard '{dash['title']}' -> uid {dash['uid']} url {url}/d/{dash['uid']}")

        # --- alert rules ---
        spec = yaml.safe_load(
            (REPO / "deploy/grafana/provisioning/alerting/ott-core-slo.yml").read_text()
        )
        existing = {r["uid"] for r in c.get("/api/v1/provisioning/alert-rules").json()}
        for group in spec["groups"]:
            for rule in group["rules"]:
                body = copy.deepcopy(rule)
                for node in body.get("data", []):
                    if node.get("datasourceUid") == LOCAL_PROM_UID:
                        node["datasourceUid"] = prom["uid"]
                body["ruleGroup"] = group["name"]
                body["folderUid"] = folder["uid"]
                body.pop("orgId", None)
                body.pop("noExistingState", None)  # "None" is not a valid state option in this API version
                # required options on the current provisioning API (field is
                # execErrState — errorState is rejected with "unknown Error
                # state option"). Values mirror the file-provisioned local rules.
                body.setdefault("noDataState", "NoData")
                body.setdefault("execErrState", "Alerting")
                body.setdefault("isPaused", False)
                if body["uid"] in existing:
                    d = c.delete(f"/api/v1/provisioning/alert-rules/{body['uid']}")
                    if d.status_code not in (200, 404):
                        print(f"  ! delete {body['uid']}: {d.status_code} {d.text[:120]}")
                p = c.post("/api/v1/provisioning/alert-rules", json=body)
                if p.status_code >= 400:
                    print(f"  ! rule {body['uid']} rejected: {p.status_code} {p.text[:500]}")
                    raise SystemExit(f"rule {body['uid']} rejected: {p.status_code} {p.text[:500]}")
                print(f"rule {body['uid']:<22s} ({body['title']}) provisioned")

        # --- verify ---
        rules = c.get("/api/v1/provisioning/alert-rules").json()
        uids = [r["uid"] for r in rules]
        expected = [r["uid"] for g in spec["groups"] for r in g["rules"]]
        missing = [u for u in expected if u not in uids]
        print(f"\nverify: {len(rules)} rules present, missing={missing or 'none'}")
        d = c.get(f"/api/dashboards/uid/{dash['uid']}")
        panels = len(d.json()["dashboard"].get("panels", []))
        print(f"verify: dashboard {d.json()['dashboard']['uid']} has {panels} panels")
        return 0 if not missing else 1


if __name__ == "__main__":
    raise SystemExit(main())
