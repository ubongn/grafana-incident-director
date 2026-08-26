"""incident_director — agentic incident loop over the Grafana stack.

Arc: DETECT -> TRIANGULATE -> DIAGNOSE -> REMEDIATE -> REPORT.
The agent's only window into the observability stack is the Grafana MCP
server (mcp-grafana, run over stdio with a Grafana service-account token).
The brain is Google ADK + Gemini (Google-only AI — no other providers).
"""

__version__ = "0.2.0"
