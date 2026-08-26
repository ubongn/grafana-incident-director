"""Unit tests: audit log (append-only, hash chain)."""

import json

from incident_director.audit import AuditLog, GENESIS


def test_append_and_read_roundtrip(tmp_path):
    log = AuditLog(tmp_path)
    log.append("run_started", "run-1", trigger={"type": "alert"})
    log.append("proposal", "run-1", phase="remediate", action="refuse")
    entries = list(log.entries())
    assert [e["event"] for e in entries] == ["run_started", "proposal"]
    assert entries[0]["prev_hash"] == GENESIS
    assert entries[1]["prev_hash"] == entries[0]["hash"]


def test_chain_verifies(tmp_path):
    log = AuditLog(tmp_path)
    for i in range(5):
        log.append("proposal", f"run-{i}", n=i, nested={"a": [1, 2]})
    ok, detail = log.verify_chain()
    assert ok, detail
    assert "5 entries" in detail


def test_tampering_detected(tmp_path):
    log = AuditLog(tmp_path)
    log.append("proposal", "run-1", action="refuse")
    log.append("gate_decision", "run-1", approved=False)
    path = log.path
    lines = path.read_text().splitlines()
    doc = json.loads(lines[0])
    doc["data"]["action"] = "execute"  # tamper with history
    lines[0] = json.dumps(doc, sort_keys=True, separators=(",", ":"))
    path.write_text("\n".join(lines) + "\n")
    ok, _ = AuditLog(tmp_path).verify_chain()
    assert not ok, "tampered chain must not verify"


def test_deletion_detected(tmp_path):
    log = AuditLog(tmp_path)
    log.append("a", "r1")
    log.append("b", "r1")
    log.append("c", "r1")
    lines = log.path.read_text().splitlines()
    log.path.write_text("\n".join([lines[0], lines[2]]) + "\n")  # delete middle
    ok, _ = AuditLog(tmp_path).verify_chain()
    assert not ok


def test_tail(tmp_path):
    log = AuditLog(tmp_path)
    for i in range(4):
        log.append("e", "r", i=i)
    assert log.tail(2)[0]["data"]["i"] == 2
    assert log.tail(2)[1]["data"]["i"] == 3
