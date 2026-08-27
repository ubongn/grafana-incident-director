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


_AI_PROVIDERS = ("gemini", "vertex")


@dataclass(frozen=True)
class Settings:
    # --- AI (Google-only, two auth paths through the same google-genai SDK) ---
    # ai_provider="gemini"  — AI Studio API key (local dev fallback)
    # ai_provider="vertex"  — Vertex AI via service-account ADC (cloud/demo;
    #                         project has $300 trial credits, no 20 req/day cap)
    ai_provider: str = "gemini"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.6-flash"  # 2.5-flash sunset for API keys 2026-08
    gemini_thinking_budget: int = 0  # <=0 -> API floor (1; 0 is rejected by Gemini 3.x)
    google_cloud_project: str = ""
    google_cloud_location: str = "us-central1"
    google_application_credentials: str = ""  # SA key file for ADC (Vertex path)

    @property
    def is_vertex(self) -> bool:
        return self.ai_provider.strip().lower() == "vertex"

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
        if self.ai_provider not in _AI_PROVIDERS:
            problems.append(f"AI_PROVIDER must be one of {_AI_PROVIDERS}")
        if self.is_vertex:
            if not self.google_cloud_project:
                problems.append("GOOGLE_CLOUD_PROJECT is not set (Vertex AI; see .env.example)")
            if not self.google_application_credentials:
                problems.append(
                    "GOOGLE_APPLICATION_CREDENTIALS is not set (Vertex AI service-account "
                    "key file, or an ambient ADC environment)"
                )
            elif not Path(self.google_application_credentials).is_file():
                problems.append(
                    f"GOOGLE_APPLICATION_CREDENTIALS is not a file: {self.google_application_credentials}"
                )
        elif not self.gemini_api_key:
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

    # AI_PROVIDER (alias PROVIDER, as in the workspace studio_mind convention)
    provider = (get("AI_PROVIDER", get("PROVIDER", "gemini")) or "gemini").strip().lower()

    return Settings(
        ai_provider=provider,
        gemini_api_key=get("GEMINI_API_KEY", "").strip(),
        # Vertex default differs: gemini-3.6-flash is AI-Studio-only today
        # (404 on Vertex us-central1); gemini-2.5-flash is GA there (probe 200).
        gemini_model=get(
            "GEMINI_MODEL",
            "gemini-2.5-flash" if provider == "vertex" else "gemini-3.6-flash",
        ).strip(),
        gemini_thinking_budget=int(get("GEMINI_THINKING_BUDGET", "0")),
        google_cloud_project=get("GOOGLE_CLOUD_PROJECT", "").strip(),
        google_cloud_location=get("GOOGLE_CLOUD_LOCATION", "us-central1").strip(),
        google_application_credentials=get("GOOGLE_APPLICATION_CREDENTIALS", "").strip(),
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


_AI_KEY_ENVVARS = ("GOOGLE_API_KEY", "GEMINI_API_KEY", "GOOGLE_GENAI_API_KEY")


def apply_ai_env(settings: Settings) -> None:
    """Export provider config where google-genai/ADK look for it.

    Google-only AI: this is the single provider seam.

    vertex  -> GOOGLE_GENAI_USE_VERTEXAI=1 + GOOGLE_CLOUD_PROJECT/LOCATION +
               GOOGLE_APPLICATION_CREDENTIALS (ADC; service-account key file).
               google-genai hard-errors if an API key env var is ALSO set, so
               those are removed. Token minting happens inside google-auth.
    gemini  -> AI Studio API key (local dev fallback). Vertex env vars are
               removed so an ambient GOOGLE_GENAI_USE_VERTEXAI can't hijack it.
    """
    if settings.is_vertex:
        for var in _AI_KEY_ENVVARS:
            os.environ.pop(var, None)
        os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "1"
        os.environ["GOOGLE_CLOUD_PROJECT"] = settings.google_cloud_project
        os.environ["GOOGLE_CLOUD_LOCATION"] = settings.google_cloud_location
        if settings.google_application_credentials:
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = settings.google_application_credentials
        return
    for var in ("GOOGLE_GENAI_USE_VERTEXAI", "GOOGLE_CLOUD_PROJECT", "GOOGLE_CLOUD_LOCATION"):
        os.environ.pop(var, None)
    os.environ.setdefault("GOOGLE_API_KEY", settings.gemini_api_key)
    os.environ.setdefault("GEMINI_API_KEY", settings.gemini_api_key)
    os.environ.setdefault("GOOGLE_GENAI_API_KEY", settings.gemini_api_key)
