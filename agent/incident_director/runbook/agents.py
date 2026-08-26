"""Phase agent factory (Google ADK LlmAgent, Gemini-only).

One agent per runbook phase. Phases that need the observability stack get an
MCPToolset bound to mcp-grafana with a phase-narrow tool filter; REMEDIATE is
deliberately tool-less — it proposes, the human gate decides, and only the
executor (not the model) touches the world.
"""

from __future__ import annotations

from google.adk.agents import LlmAgent
from google.genai import types as genai_types

from ..config import Settings
from ..grafana import ALL_PHASE_TOOLS, grafana_mcp_toolset

ROLES = {
    "detect": "You are the DETECT step of an SRE incident director. Read alert state through Grafana MCP tools and report it as structured JSON.",
    "triangulate": "You are the TRIANGULATE step of an SRE incident director. Quantify blast radius with dashboard/panel PromQL through Grafana MCP tools and report structured JSON.",
    "diagnose": "You are the DIAGNOSE step of an SRE incident director. Ground the root cause in Loki log evidence through Grafana MCP tools and report structured JSON.",
    "remediate": "You are the REMEDIATE step of an SRE incident director. You propose a minimal, reversible remediation (or a justified refusal) as structured JSON. You never execute.",
    "report": "You are the REPORT step of an SRE incident director. Post the annotation, verify, and write the incident report as structured JSON.",
}


def generate_content_config(settings: Settings) -> genai_types.GenerateContentConfig:
    # budget 0 ("no thinking") is INVALID_ARGUMENT on Gemini 3.x — the API
    # floor is 1. 1 is the nearest-to-off value valid on both 2.5 and 3.x.
    budget = settings.gemini_thinking_budget
    if budget <= 0:
        budget = 1
    return genai_types.GenerateContentConfig(
        temperature=0.0,
        thinking_config=genai_types.ThinkingConfig(thinking_budget=budget),
    )


def build_phase_agent(settings: Settings, phase: str) -> LlmAgent:
    if phase not in ROLES:
        raise ValueError(f"unknown phase: {phase}")
    tools: list = []
    if phase in ALL_PHASE_TOOLS:
        tools.append(grafana_mcp_toolset(settings, phase))
    return LlmAgent(
        name=f"incident_{phase}",
        model=settings.gemini_model,
        instruction=ROLES[phase],
        tools=tools,
        generate_content_config=generate_content_config(settings),
        output_key=f"{phase}_out",
    )


async def close_agent_tools(agent: LlmAgent) -> None:
    """Tear down MCP child processes owned by an agent's toolsets."""
    for tool in agent.tools or []:
        close = getattr(tool, "close", None)
        if close is not None:
            try:
                result = close()
                if hasattr(result, "__await__"):
                    await result
            except Exception:  # pragma: no cover - cleanup must never raise
                pass
