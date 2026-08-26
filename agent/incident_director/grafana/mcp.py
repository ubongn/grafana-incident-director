"""Grafana MCP toolset factory — the agent's only window into the stack.

The OSS `mcp-grafana` server is spawned over stdio per phase agent with a
Grafana service-account token. Each phase gets a narrow allowlist via
`tool_filter` so the model sees only the tools its runbook step needs
(deterministic tool use, fewer tokens, tighter demo timing).

This module is also the compliance surface: every read of alert state, every
dashboard/panel query and every Loki query the agent performs flows through
these MCP toolsets at runtime.
"""

from __future__ import annotations

import os
from typing import Iterable

from google.adk.tools.mcp_tool.mcp_toolset import (
    MCPToolset,
    StdioServerParameters,
)

from ..config import Settings

# Phase tool allowlists (names as exposed by mcp-grafana v1.2.0, 68 tools).
DETECT_TOOLS = ("list_alert_groups", "get_alert_group", "get_annotations")
TRIANGULATE_TOOLS = (
    "search_dashboards",
    "get_dashboard_by_uid",
    "get_dashboard_panel_queries",
    "get_dashboard_summary",
    "query_prometheus",
    "list_prometheus_metric_names",
    "list_prometheus_label_values",
)
DIAGNOSE_TOOLS = (
    "query_loki_logs",
    "list_loki_label_names",
    "list_loki_label_values",
    "query_loki_patterns",
    "find_error_pattern_logs",
    "query_prometheus",
)
REPORT_TOOLS = (
    "create_annotation",
    "query_prometheus",
    "generate_deeplink",
    "get_dashboard_by_uid",
)

ALL_PHASE_TOOLS = {
    "detect": DETECT_TOOLS,
    "triangulate": TRIANGULATE_TOOLS,
    "diagnose": DIAGNOSE_TOOLS,
    "report": REPORT_TOOLS,
}


def mcp_server_params(settings: Settings) -> StdioServerParameters:
    """Server params for one mcp-grafana stdio child process."""
    command, args = settings.mcp_resolved_command
    env = {
        # child gets PATH (to find uv/node) but no other ambient secrets
        **{k: v for k, v in os.environ.items() if k.upper() == "PATH"},
        "GRAFANA_URL": settings.grafana_url,
        "GRAFANA_SERVICE_ACCOUNT_TOKEN": settings.grafana_token,
    }
    return StdioServerParameters(command=command, args=args, env=env)


def grafana_mcp_toolset(
    settings: Settings,
    phase: str,
    extra_tools: Iterable[str] = (),
) -> MCPToolset:
    """Build the MCPToolset for one phase (its own mcp-grafana process)."""
    names = ALL_PHASE_TOOLS.get(phase, tuple(extra_tools))
    if extra_tools:
        names = tuple(dict.fromkeys((*names, *extra_tools)))
    return MCPToolset(
        stdio_server_params=mcp_server_params(settings),
        tool_filter=list(names),
    )
