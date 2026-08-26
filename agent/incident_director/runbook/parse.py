"""Lenient extraction + validation of phase-agent JSON output.

ADK agents that carry tools cannot also force an output schema, so phase
agents are instructed to end their final message with a JSON object. This
module extracts that JSON robustly (fenced or bare) and validates it against
the phase's pydantic model. The orchestrator retries a phase once on failure.
"""

from __future__ import annotations

import json
import re
from typing import TypeVar

from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)

_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)
_OBJ_RE = re.compile(r"\{.*\}", re.DOTALL)


class PhaseParseError(Exception):
    pass


def extract_json(text: str) -> dict:
    """Pull the first plausible JSON object out of an LLM message."""
    if not text or not text.strip():
        raise PhaseParseError("empty response")
    for candidate in _FENCE_RE.findall(text):
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    # bare object: take the outermost braces (agents are told JSON is final)
    m = _OBJ_RE.search(text)
    if not m:
        raise PhaseParseError("no JSON object found")
    raw = m.group(0)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # tolerate trailing prose inside/after braces by balancing scans
        for end in range(len(raw) - 1, 0, -1):
            if raw[end] == "}":
                try:
                    return json.loads(raw[: end + 1])
                except json.JSONDecodeError:
                    continue
        raise PhaseParseError("unparseable JSON object") from None


def validate(model: type[T], text: str) -> T:
    """Extract + validate. Raises PhaseParseError with a compact reason."""
    try:
        data = extract_json(text)
    except PhaseParseError:
        raise
    try:
        return model.model_validate(data)
    except ValidationError as e:
        problems = "; ".join(
            f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in e.errors()[:5]
        )
        raise PhaseParseError(f"schema violation: {problems}") from None
