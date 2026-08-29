"""Provision the OTT dashboard + SLO alert rules into Grafana Cloud via API.

Reads the same artifacts the local stack file-provisions
(deploy/grafana/dashboards/ott-streaming-ops.json and
deploy/grafana/provisioning/alerting/ott-core-slo.yml), rewrites datasource
uids to the stack's hosted Prometheus/Loki, and pushes them through the
Grafana HTTP API with a service-account token (Admin). Idempotent: re-running
overwrites the dashboard and replaces rules with matching uids.

Datasources: ensures `prom-ott` + `loki-ott` exist and point at the stack's
hosted Prometheus (https://…/api/prom) and Loki (https://logs-prod-…), basic
auth = <instance-id>:<cloud api key>. These uids match the ones the agent's
runbook prompts and probe payloads use, so the SAME agent code runs unchanged
against local and cloud.

Creds come from the staged grafana-cloud-creds.txt at the workspace root
(never committed) or from env:
  GRAFANA_URL, GRAFANA_SERVICE_ACCOUNT_TOKEN,
  PROM_QUERY_URL, PROM_USER, LOKI_PUSH_URL, LOKI_USER, GRAFANA_CLOUD_API_KEY

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

PROM_UID = "prom-ott"  # uid shared by local file-provisioning, agent prompts, cloud
LOKI_UID = "loki-ott"
_KEYS = (
    "GRAFANA_URL",
    "PROM_QUERY_URL",
    "PROM_USER",
    "LOKI_PUSH_URL",
    "LOKI_USER",
    "GRAFANA_CLOUD_API_KEY",
)
_TOKEN_KEYS = ("GRAFANA_SERVICE_ACCOUNT_TOKEN", "GRAFANA_SA_TOKEN")  # long name / creds-file alias


def load_creds(arg: str | None) -> dict[str, str]:
    if arg:
        creds: dict[str, str] = {}
        for line in Path(arg).read_text().splitlines():
            m = re.match(rf"^({'|'.join(_KEYS + _TOKEN_KEYS)})=(\S+)$", line.strip())
            if m:
                creds[m.group(1)] = m.group(2)
        creds["GRAFANA_SERVICE_ACCOUNT_TOKEN"] = creds.get(
            "GRAFANA_SERVICE_ACCOUNT_TOKEN"
        ) or creds.get("GRAFANA_SA_TOKEN", "")
        missing = [k for k in (*_KEYS, "GRAFANA_SERVICE_ACCOUNT_TOKEN") if not creds.get(k)]
        if missing:
            raise SystemExit(f"creds file missing keys: {missing}")
        return creds

    import os

    creds = {k: os.environ.get(k, "") for k in _KEYS}
    creds["GRAFANA_SERVICE_ACCOUNT_TOKEN"] = os.environ.get(
        "GRAFANA_SERVICE_ACCOUNT_TOKEN"
    ) or os.environ.get("GRAFANA_SA_TOKEN", "")
    missing = [k for k in (*_KEYS, "GRAFANA_SERVICE_ACCOUNT_TOKEN") if not creds[k]]
    if missing:
        raise SystemExit(
            "no creds: pass the creds file path or set " + ", ".join((*_KEYS, *_TOKEN_KEYS))
        )
    return creds


def ensure_datasource(c: httpx.Client, *, uid: str, name: str, type_: str, url: str, user: str, key: str) -> None:
    """Create (or repair) a basic-auth datasource with a fixed uid."""
    body = {
        "uid": uid,
        "name": name,
        "type": type_,
        "url": url,
        "access": "proxy",
        "basicAuth": True,
        "basicAuthUser": user,
        "secureJsonData": {"basicAuthPassword": key},
        "jsonData": {"httpMethod": "POST"},  # required for hosted Prom/Loki
        "readOnly": False,
    }
    cur = c.get(f"/api/datasources/uid/{uid}")
    if cur.status_code == 404:
        r = c.post("/api/datasources", json=body)
        r.raise_for_status()
        print(f"datasource {uid} created ({type_} -> {url}, user {user})")
    else:
        cur.raise_for_status()
        j = cur.json()
        patch = {
            k: v
            for k, v in body.items()
            if k not in ("secureJsonData",) and j.get(k) != v
        }
        if patch or j.get("basicAuthUser") != user:
            r = c.put(f"/api/datasources/uid/{uid}", json=body)
            r.raise_for_status()
            print(f"datasource {uid} updated (drift: {sorted(patch) or 'auth'})")
        else:
            print(f"datasource {uid} ok ({type_} -> {url})")
    h = c.get(f"/api/datasources/uid/{uid}/health")
    ok = h.status_code == 200 and h.json().get("status") in ("OK", "SUCCESS")
    print(f"datasource {uid} health: {h.status_code} {h.json().get('status') or h.json().get('message', '')[:80]}")
    if not ok:
        raise SystemExit(f"datasource {uid} unhealthy — fix before continuing")


def main() -> int:
    creds = load_creds(sys.argv[1] if len(sys.argv) > 1 else None)
    url = creds["GRAFANA_URL"].rstrip("/")
    headers = {"Authorization": f"Bearer {creds['GRAFANA_SERVICE_ACCOUNT_TOKEN']}", "Content-Type": "application/json"}
    loki_base = creds["LOKI_PUSH_URL"].replace("/loki/api/v1/push", "")

    with httpx.Client(timeout=60.0, headers=headers, base_url=url) as c:
        # --- datasources (fixed uids; agent prompts depend on them) ---
        ensure_datasource(
            c, uid=PROM_UID, name="OTT Prometheus (hosted)", type_="prometheus",
            url=creds["PROM_QUERY_URL"], user=creds["PROM_USER"], key=creds["GRAFANA_CLOUD_API_KEY"],
        )
        ensure_datasource(
            c, uid=LOKI_UID, name="OTT Loki (hosted)", type_="loki",
            url=loki_base, user=creds["LOKI_USER"], key=creds["GRAFANA_CLOUD_API_KEY"],
        )

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
        raw = dash_path.read_text().replace(LOKI_UID, LOKI_UID)  # loki refs (future) stay canonical
        dash = json.loads(raw.replace("prom-ott", PROM_UID))
        r = c.post(
            "/api/dashboards/db",
            json={"dashboard": dash, "folderUid": folder["uid"], "overwrite": True,
                  "message": "provisioned by provision_cloud.py (M3-final)"},
        )
        r.raise_for_status()
        print(f"dashboard '{dash['title']}' -> uid {dash['uid']} url {url}/d/{dash['uid']}")

        # --- agent self-observability dashboard (same folder, same uids) ---
        obs_path = REPO / "deploy/grafana/dashboards/agent-observability.json"
        obs = json.loads(obs_path.read_text())
        r = c.post(
            "/api/dashboards/db",
            json={"dashboard": obs, "folderUid": folder["uid"], "overwrite": True,
                  "message": "provisioned by provision_cloud.py (agent-observability)"},
        )
        r.raise_for_status()
        print(f"dashboard '{obs['title']}' -> uid {obs['uid']} url {url}/d/{obs['uid']}")

        # --- alert rules (delete+repost keeps this idempotent on re-runs) ---
        spec = yaml.safe_load(
            (REPO / "deploy/grafana/provisioning/alerting/ott-core-slo.yml").read_text()
        )
        existing = {r["uid"] for r in c.get("/api/v1/provisioning/alert-rules").json()}
        for group in spec["groups"]:
            for rule in group["rules"]:
                body = copy.deepcopy(rule)
                for node in body.get("data", []):
                    if node.get("datasourceUid") == "prom-ott":
                        node["datasourceUid"] = PROM_UID
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
                    if d.status_code not in (200, 204, 404):
                        print(f"  ! delete {body['uid']}: {d.status_code} {d.text[:120]}")
                p = c.post("/api/v1/provisioning/alert-rules", json=body)
                if p.status_code >= 400:
                    print(f"  ! rule {body['uid']} rejected: {p.status_code} {p.text[:500]}")
                    raise SystemExit(f"rule {body['uid']} rejected: {p.status_code} {p.text[:500]}")
                print(f"rule {body['uid']:<22s} ({body['title']}) provisioned")

        # --- notifications ---
        # Hosted Alertmanager is NOT configured on this stack (404), and there
        # is no consented email/webhook sink — so no contact point is created.
        # "Firing visibly" is covered by rule state in the Alerting UI + the
        # auto-provisioned 'Alert Groups Insights' state-history dashboard.
        am = c.get("/api/alertmanager/grafana/config/api/v1/status")
        cps = c.get("/api/v1/provisioning/contact-points").json()
        print(f"alertmanager: {'enabled' if am.status_code == 200 else 'not configured'}; "
              f"contact points: {len(cps)} (left as-is)")

        # --- verify ---
        rules = c.get("/api/v1/provisioning/alert-rules").json()
        uids = [r["uid"] for r in rules]
        expected = [r["uid"] for g in spec["groups"] for r in g["rules"]]
        missing = [u for u in expected if u not in uids]
        ds_ok = all(
            r["data"][0]["datasourceUid"] == PROM_UID
            for r in rules
            if r["uid"] in expected
        )
        print(f"\nverify: {len(rules)} rules present, missing={missing or 'none'}, "
              f"datasource={PROM_UID if ds_ok else 'MISMATCH'}")
        d = c.get(f"/api/dashboards/uid/{dash['uid']}")
        panels = len(d.json()["dashboard"].get("panels", []))
        print(f"verify: dashboard {d.json()['dashboard']['uid']} has {panels} panels")
        return 0 if (not missing and ds_ok and panels == 15) else 1


if __name__ == "__main__":
    raise SystemExit(main())
