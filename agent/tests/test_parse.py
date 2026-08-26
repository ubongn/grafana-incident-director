"""Unit tests: phase JSON extraction/validation."""

import pytest

from incident_director.models import DetectionResult, RemediationProposal
from incident_director.runbook.parse import PhaseParseError, extract_json, validate


def test_fenced_json():
    text = 'Blah blah\n```json\n{"has_incident": true, "summary": "x"}\n```\n'
    assert extract_json(text) == {"has_incident": True, "summary": "x"}


def test_bare_json_with_prose():
    text = 'Here is my answer: {"has_incident": false, "summary": "ok"} hope that helps'
    assert extract_json(text)["has_incident"] is False


def test_nested_braces():
    text = '{"alerts": [{"rule_name": "a", "state": "firing"}], "has_incident": true, "summary": "s"}'
    data = extract_json(text)
    assert data["alerts"][0]["state"] == "firing"


def test_no_json_raises():
    with pytest.raises(PhaseParseError):
        extract_json("no json here at all")


def test_empty_raises():
    with pytest.raises(PhaseParseError):
        extract_json("   ")


def test_validate_ok():
    obj = validate(DetectionResult, '{"has_incident": true, "summary": "burning", '
                   '"alerts": [{"rule_name": "Playback error rate burning SLO", "state": "firing"}]}')
    assert obj.has_incident and obj.alerts[0].rule_name.startswith("Playback")


def test_validate_schema_violation_names_field():
    with pytest.raises(PhaseParseError, match="schema violation"):
        validate(DetectionResult, '{"summary": "missing has_incident"}')


def test_validate_proposal_enum_guard():
    with pytest.raises(PhaseParseError):
        validate(RemediationProposal,
                 '{"action": "execute", "remediation_class": "restart_everything", "rationale": "x"}')


def test_validate_strips_pending_alerts():
    obj = validate(DetectionResult, '{"has_incident": false, "summary": "s", "alerts": ['
                   '{"rule_name": "a", "state": "normal"}, {"rule_name": "b", "state": "firing"}]}')
    assert [a.rule_name for a in obj.alerts] == ["b"]
