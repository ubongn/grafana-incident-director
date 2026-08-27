"""Vertex probe — fail fast before wiring anything.

1. Confirm where google-genai reads Vertex env config (so we know which env
   vars ADK's client will honor).
2. Mint a token from the staged service-account key via google-auth and make
   raw REST generate calls against Vertex for candidate models.
Prints one line per model: HTTP status + model name + reply head.
"""

from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

KEY_PATH = Path(r"C:\Users\Sabiedu\.qwenpaw\workspaces\hack_3\vertex-key.json")
PROJECT = "agentic-cinema-506710"
LOCATION = "us-central1"
MODELS = sys.argv[1:] or ["gemini-2.5-flash", "gemini-3.6-flash"]


def where_genai_reads_env() -> list[str]:
    import google.genai as g

    pkg = Path(g.__file__).parent
    hits: list[str] = []
    for p in sorted(pkg.rglob("*.py")):
        for i, line in enumerate(
            p.read_text(encoding="utf-8", errors="ignore").splitlines(), 1
        ):
            if any(
                s in line
                for s in (
                    "GOOGLE_GENAI_USE_VERTEXAI",
                    "GOOGLE_CLOUD_PROJECT",
                    "GOOGLE_CLOUD_LOCATION",
                    "GOOGLE_APPLICATION_CREDENTIALS",
                )
            ):
                hits.append(f"  {p.name}:{i}: {line.strip()[:120]}")
    return hits


def rest_generate(model: str, token: str) -> tuple[int, str]:
    url = (
        f"https://{LOCATION}-aiplatform.googleapis.com/v1/projects/{PROJECT}"
        f"/locations/{LOCATION}/publishers/google/models/{model}:generateContent"
    )
    body = json.dumps(
        {
            "contents": [{"role": "user", "parts": [{"text": "Reply with exactly: PONG"}]}],
            "generationConfig": {"temperature": 0.0},
        }
    ).encode()
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            payload = json.loads(r.read())
            text = payload.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")
            return r.status, text.strip()[:60]
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="ignore")[:200]
        return e.code, detail
    except Exception as e:  # noqa: BLE001
        return -1, repr(e)


def main() -> int:
    print("== google-genai env seams ==")
    for h in where_genai_reads_env():
        print(h)

    print("\n== minting SA token via google-auth ==")
    try:
        import google.auth.transport.requests
        from google.oauth2 import service_account

        creds = service_account.Credentials.from_service_account_file(
            str(KEY_PATH),
            scopes=["https://www.googleapis.com/auth/cloud-platform"],
        )
        creds.refresh(google.auth.transport.requests.Request())
        print(f"  token OK: {creds.token[:12]}...  ({KEY_PATH.name})")
    except Exception as e:  # noqa: BLE001
        print(f"  FAIL: {e!r}")
        return 2

    print("\n== raw Vertex generateContent probes ==")
    ok = False
    for model in MODELS:
        status, text = rest_generate(model, creds.token)
        print(f"  [{status}] {model}: {text}")
        if status == 200:
            ok = True
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
