"""Probe the real Grafana Cloud stack using the staged creds file.

Usage: python deploy/cloud_probe.py --cloud
"""
from __future__ import annotations

import base64
import json
import os
import re
import sys
from pathlib import Path

import httpx

REPO = Path(__file__).resolve().parents[1]

# --- parse the staged creds file (never committed) ---
creds = {}
for line in (Path(os.environ.get("CREDS", REPO.parent / "grafana-cloud-creds.txt"))).read_text().splitlines():
    m = re.match(r"^([A-Z_]+)=(\S+)$", line.strip())
    if m:
        creds[m.group(1)] = m.group(2)

GURL = creds["GRAFANA_URL"].rstrip("/")
GLSA = creds["GRAFANA_SA_TOKEN"]
PROM_RW = creds["PROM_REMOTE_WRITE_URL"]
PROM_Q = creds["PROM_QUERY_URL"]
LOKI = creds["LOKI_PUSH_URL"]
PROM_USER = creds["PROM_USER"]
LOKI_USER = creds["LOKI_USER"]
KEY = creds["GRAFANA_CLOUD_API_KEY"]

basic_prom = base64.b64encode(f"{PROM_USER}:{KEY}".encode()).decode()
basic_loki = base64.b64encode(f"{LOKI_USER}:{KEY}".encode()).decode()

with httpx.Client(timeout=20.0) as c:
    me = c.get(f"{GURL}/api/user", headers={"Authorization": f"Bearer {GLSA}"})
    print("grafana whoami:", me.status_code, me.json().get("login"), me.json().get("orgRole"))

    ds = c.get(f"{GURL}/api/datasources", headers={"Authorization": f"Bearer {GLSA}"})
    print("datasources:", ds.status_code)
    for d in ds.json():
        print(f"  - uid={d['uid']:45s} type={d['type']:12s} name={d['name']:45s} default={d.get('isDefault')}")

    for path in ("/api/v1/provisioning/alert-rules", "/api/v1/provisioning/alert-rule-groups"):
        r = c.get(f"{GURL}{path}", headers={"Authorization": f"Bearer {GLSA}"})
        n = len(r.json()) if r.status_code == 200 else r.text[:120]
        print(path, "->", r.status_code, n)

    folders = c.get(f"{GURL}/api/folders", headers={"Authorization": f"Bearer {GLSA}"})
    print("folders:", folders.status_code, [f["title"] for f in folders.json()][:10])

    dash = c.get(f"{GURL}/api/search?query=OTT", headers={"Authorization": f"Bearer {GLSA}"})
    print("dashboards matching OTT:", [(d["uid"], d["title"]) for d in dash.json()])

    # prometheus query check
    q = c.get(f"{PROM_Q}/api/v1/query", params={"query": "up"},
              headers={"Authorization": f"Basic {basic_prom}"})
    print("prom instant query 'up':", q.status_code, json.dumps(q.json().get("data", {}).get("result"))[:200])

    # loki labels check
    lb = c.get(f"{LOKI.rsplit('/loki', 1)[0]}/loki/api/v1/labels",
               headers={"Authorization": f"Basic {basic_loki}"})
    print("loki labels:", lb.status_code, lb.text[:200])
