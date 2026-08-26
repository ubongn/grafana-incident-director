"""Environment-driven configuration.

All values come from `.env` (gitignored) / process env. Never hardcode secrets.
Loading this module must not require credentials — only runtime phases do.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_repo_env() -> None:
    load_dotenv(REPO_ROOT / ".env", override=False)


_APPROVAL_MODES = ("interactive", "refuse_unattended", "auto_approve")


@dataclass(frozen=True)
class Settings:
    # --- AI (Google-only) ---
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.6-flash"  # 2.5-flash sunset for API keys 2026-08
    gemini_thinking_budget: int = 0  # <=0 -> API floor (1; 0 is rejected by Gemini 3.x)

    # --- Grafana & MCP ---
    grafana_url: str = "http://localhost:3001"
    grafana_token: str = ""
    mcp_command: str = ""  # resolved at runtime if empty (mcp-grafana -> uvx fallback)
    mcp_args: tuple[str, ...] = ("server",)

    # --- Telemetry simulator (fault injection + remediation target) ---
    sim_control_url: str = "http://localhost:8790"

    # --- Runtime behaviour ---
    approval_mode: str = "interactive"  # interactive | refuse_unattended | auto_approve
    demo_mode: bool = False
    audit_dir: Path = field(default_factory=lambda: REPO_ROOT / "audit")
    phase_timeout_s: float = 90.0
    phase_retries: int = 1
    log_level: str = "info"

    @property
    def mcp_resolved_command(self) -> tuple[str, list[str]]:
        """Resolve the mcp-grafana launch command.

        Preference: explicit env override > installed `mcp-grafana` binary >
        `uvx mcp-grafana@latest` fallback.
        """
        if self.mcp_command:
            return self.mcp_command, list(self.mcp_args)
        found = shutil.which("mcp-grafana")
        if found:
            return found, list(self.mcp_args)
        return "uvx", ["mcp-grafana@latest", *self.mcp_args]

    def validate_runtime(self) -> list[str]:
        """Return a list of human-readable blocking problems (empty = ok)."""
        problems: list[str] = []
        if not self.gemini_api_key:
            problems.append("GEMINI_API_KEY is not set (AI Studio key; see .env.example)")
        if not self.grafana_token:
            problems.append("GRAFANA_SERVICE_ACCOUNT_TOKEN is not set (see .env.example)")
        if self.approval_mode not in _APPROVAL_MODES:
            problems.append(f"APPROVAL_MODE must be one of {_APPROVAL_MODES}")
        if self.approval_mode == "auto_approve" and os.environ.get("ALLOW_AUTO_APPROVE") != "1":
            problems.append("APPROVAL_MODE=auto_approve requires ALLOW_AUTO_APPROVE=1 (double opt-in)")
        return problems


def load_settings(env: dict[str, str] | None = None) -> Settings:
    """Build Settings from .env + process env (or an explicit env dict for tests)."""
    if env is None:
        _load_repo_env()
        get = os.environ.get
    else:
        get = env.get  # type: ignore[assignment]

    def flag(name: str, default: str = "0") -> bool:
        return get(name, default).strip().lower() in ("1", "true", "yes", "on")

    return Settings(
        gemini_api_key=get("GEMINI_API_KEY", "").strip(),
        gemini_model=get("GEMINI_MODEL", "gemini-3.6-flash").strip(),
        gemini_thinking_budget=int(get("GEMINI_THINKING_BUDGET", "0")),
        grafana_url=get("GRAFANA_URL", "http://localhost:3001").strip().rstrip("/"),
        grafana_token=get("GRAFANA_SERVICE_ACCOUNT_TOKEN", "").strip(),
        mcp_command=get("MCP_GRAFANA_COMMAND", "").strip(),
        mcp_args=tuple(
            s.strip() for s in get("MCP_GRAFANA_ARGS", "server").split() if s.strip()
        ),
        sim_control_url=get("SIM_CONTROL_URL", "http://localhost:8790").strip().rstrip("/"),
        approval_mode=get("APPROVAL_MODE", "interactive").strip(),
        demo_mode=flag("DEMO_MODE"),
        audit_dir=Path(get("AUDIT_DIR", str(REPO_ROOT / "audit"))),
        phase_timeout_s=float(get("PHASE_TIMEOUT_S", "90")),
        phase_retries=int(get("PHASE_RETRIES", "1")),
        log_level=get("AGENT_LOG_LEVEL", "info").strip().lower(),
    )


def apply_ai_env(settings: Settings) -> None:
    """Export the Gemini key where google-genai/ADK look for it.

    Google-only AI: this is the single provider seam. Vertex AI swap is
    config-only (GOOGLE_GENAI_USE_VERTEXAI etc.) and needs no code change.
    """
    os.environ.setdefault("GOOGLE_API_KEY", settings.gemini_api_key)
    os.environ.setdefault("GEMINI_API_KEY", settings.gemini_api_key)
    os.environ.setdefault("GOOGLE_GENAI_API_KEY", settings.gemini_api_key)
    # never accidentally take the Vertex/ADC path when an AI Studio key is set
    os.environ.pop("GOOGLE_GENAI_USE_VERTEXAI", None)
    os.environ.pop("GOOGLE_VERTEXAI_PROJECT", None)
