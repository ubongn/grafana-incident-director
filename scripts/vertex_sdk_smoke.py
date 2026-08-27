"""One-shot SDK smoke: env-configured google-genai Client -> Vertex generate.

This is the exact path ADK's Gemini model takes (api_client -> google.genai
Client with no explicit args -> env vars). Proves the wiring without running
a full arc phase. Prints status + model + reply.
"""

from __future__ import annotations

import asyncio

from incident_director.config import apply_ai_env, load_settings


async def main() -> int:
    settings = load_settings()
    apply_ai_env(settings)

    from google.genai import Client

    client = Client()  # env-configured (GOOGLE_GENAI_USE_VERTEXAI=1 + ADC)
    resp = await client.aio.models.generate_content(
        model=settings.gemini_model,
        contents="Reply with exactly: PONG",
    )
    text = (resp.text or "").strip()
    print(f"[OK] model={settings.gemini_model} provider={settings.ai_provider} -> {text!r}")
    return 0 if "PONG" in text else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
