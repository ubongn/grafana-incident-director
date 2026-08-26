"""Phase models — the structured outputs of the incident arc.

Every phase agent finishes with a JSON message validated against one of these
models. Keeping them strict is what makes the eval harness deterministic:
decisions are compared as data, not prose.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

# The closed set of remediation classes. Mirrors sim/src/remediation.js.
RemediationClass = Literal[
    "drain_cdn_edge",
    "failover_origin",
    "switch_license_endpoint",
    "throttle_ingest",
    "tighten_abr_floor",
    "none",
]

Scope = Literal["global", "regional", "component", "none"]


class AlertFact(BaseModel):
    """One alert as observed through the Grafana MCP server."""

    rule_uid: str = ""
    rule_name: str
    state: str  # firing | pending | ...
    severity: str = ""
    labels: dict[str, str] = Field(default_factory=dict)
    summary: str = ""


class DetectionResult(BaseModel):
    """DETECT: what is firing right now?"""

    has_incident: bool
    alerts: list[AlertFact] = Field(default_factory=list)
    benign_elevation: bool = False  # traffic up but budgets intact (trap signature)
    summary: str

    @field_validator("alerts")
    @classmethod
    def _drop_pending(cls, v: list[AlertFact]) -> list[AlertFact]:
        return [a for a in v if a.state.lower() != "normal"]


class Finding(BaseModel):
    """One quantified signal from the dashboards (TRIANGULATE)."""

    signal: str  # e.g. "playback error ratio by region"
    query: str = ""  # the PromQL actually run
    evidence: str  # what was observed, values included
    in_budget: bool = True


class Hypothesis(BaseModel):
    name: str
    likelihood: float = Field(ge=0.0, le=1.0)
    rationale: str = ""


class TriangulationResult(BaseModel):
    """TRIANGULATE: blast radius + ranked hypotheses."""

    scope: Scope
    findings: list[Finding] = Field(default_factory=list)
    affected_regions: list[str] = Field(default_factory=list)
    affected_edges: list[str] = Field(default_factory=list)
    affected_origins: list[str] = Field(default_factory=list)
    affected_platforms: list[str] = Field(default_factory=list)
    hypotheses: list[Hypothesis] = Field(default_factory=list)
    summary: str


class DiagnosisResult(BaseModel):
    """DIAGNOSE: root cause grounded in log evidence."""

    root_cause: str
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: list[str] = Field(default_factory=list)  # quoted log lines / selectors
    remediation_class: RemediationClass
    rationale: str = ""


class RemediationProposal(BaseModel):
    """REMEDIATE: the gated decision. `refuse` is a first-class outcome."""

    action: Literal["execute", "refuse"]
    remediation_class: RemediationClass
    params: dict[str, str] = Field(default_factory=dict)
    rationale: str
    expected_effect: str = ""
    risk: str = ""
    rollback: str = ""

    @property
    def is_no_action(self) -> bool:
        return self.action == "refuse" or self.remediation_class == "none"


class ReportResult(BaseModel):
    """REPORT: annotation posted + verification + human-readable report."""

    annotation_id: str = ""
    dashboard_uid: str = ""
    verification: str = ""  # what the post-action check showed
    markdown: str
    follow_ups: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Pipeline-level records (not produced by any LLM)
# ---------------------------------------------------------------------------


class PhaseRecord(BaseModel):
    """Per-phase telemetry captured by the orchestrator (audit + evals)."""

    phase: str
    ok: bool
    seconds: float
    tool_calls: list[str] = Field(default_factory=list)
    attempts: int = 1
    error: str = ""
