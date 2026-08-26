"""Enumerate the tools exposed by mcp-grafana against a Grafana instance.

Usage:
    python scripts/mcp_probe.py [--call list_dashboards]

Spawns `uvx mcp-grafana` over stdio (exactly how ADK's MCPToolset will run it),
initializes the session, lists tools, and optionally calls one.
"""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

REPO_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(REPO_ROOT / ".env")

GRAFANA_URL = os.environ.get("GRAFANA_URL", "http://localhost:3001")
GRAFANA_TOKEN = os.environ.get("GRAFANA_SERVICE_ACCOUNT_TOKEN", "")


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--call", help="tool name to call after listing")
    parser.add_argument("--args", default="{}", help="JSON arguments for --call")
    parser.add_argument("--args-file", help="path to JSON file with arguments for --call")
    args = parser.parse_args()

    call_args = {}
    if args.args_file:
        call_args = json.loads(Path(args.args_file).read_text())
    elif args.call:
        call_args = json.loads(args.args)

    env = {
        **{k: v for k, v in os.environ.items() if k.upper().startswith("PATH")},
        "GRAFANA_URL": GRAFANA_URL,
        "GRAFANA_SERVICE_ACCOUNT_TOKEN": GRAFANA_TOKEN,
    }

    params = StdioServerParameters(command="uvx", args=["mcp-grafana@latest"], env=env)

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()

            print(f"=== {len(tools.tools)} tools from mcp-grafana ===")
            for t in tools.tools:
                schema = ""
                try:
                    props = t.inputSchema.get("properties", {})
                    schema = ", ".join(f"{k}:{v.get('type', '?')}" for k, v in props.items())
                except Exception:
                    pass
                print(f"- {t.name}({schema})")

            if args.call:
                print(f"\n=== calling {args.call} ===")
                result = await session.call_tool(args.call, call_args)
                for c in result.content:
                    text = getattr(c, "text", None)
                    print(text[:2000] if text else repr(c))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
