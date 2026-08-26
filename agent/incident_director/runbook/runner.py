"""ADK runner wrapper: one phase agent -> final text + MCP tool-call trace.

The tool-call trace is first-class output: the orchestrator audits it and the
eval harness reports it as compliance evidence ("the agent really used the
Grafana MCP server at runtime").
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from google.adk.agents import LlmAgent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types as genai_types

APP_NAME = "incident-director"
USER_ID = "operator"


@dataclass
class PhaseOutput:
    text: str = ""
    tool_calls: list[str] = field(default_factory=list)
    tool_traces: list[dict] = field(default_factory=list)  # {name, args} for audit


def _event_text(event) -> str:
    content = getattr(event, "content", None) or getattr(event, "message", None)
    if content is None:
        return ""
    parts = getattr(content, "parts", None) or []
    texts = [getattr(p, "text", "") or "" for p in parts]
    return "".join(t for t in texts if t)


async def run_phase_agent(
    agent: LlmAgent,
    prompt: str,
    timeout_s: float,
    session_manager: InMemorySessionService | None = None,
) -> PhaseOutput:
    session_manager = session_manager or InMemorySessionService()
    session = await session_manager.create_session(app_name=APP_NAME, user_id=USER_ID)
    runner = Runner(app_name=APP_NAME, agent=agent, session_service=session_manager)
    message = genai_types.Content(role="user", parts=[genai_types.Part(text=prompt)])

    out = PhaseOutput()

    async def consume() -> None:
        async for event in runner.run_async(
            user_id=USER_ID, session_id=session.id, new_message=message
        ):
            for call in event.get_function_calls() or []:
                out.tool_calls.append(call.name)
                out.tool_traces.append(
                    {"name": call.name, "args": _safe_args(call)}
                )
            for resp in event.get_function_responses() or []:
                if not out.tool_calls or resp.name != out.tool_calls[-1]:
                    out.tool_calls.append(resp.name)
                    out.tool_traces.append({"name": resp.name, "args": None})
            if event.is_final_response():
                text = _event_text(event)
                if text:
                    out.text = text

    try:
        await asyncio.wait_for(consume(), timeout=timeout_s)
    finally:
        pass
    return out


def _safe_args(call) -> dict | None:
    args = getattr(call, "args", None)
    if isinstance(args, dict):
        clean = {}
        for k, v in args.items():
            clean[str(k)] = v if isinstance(v, (str, int, float, bool)) else str(v)
        return clean
    return None
