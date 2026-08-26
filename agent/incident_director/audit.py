"""Append-only audit log (JSONL) with a tamper-evident hash chain.

Every proposal, gate decision, execution and report lands here. The chain is
sha256 over the canonical JSON of each entry including the previous hash, so
any edit or deletion of history is detectable via `verify_chain()`.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Iterator

GENESIS = "0" * 64


def canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def entry_hash(prev: str, entry: dict[str, Any]) -> str:
    return hashlib.sha256((prev + canonical(entry)).encode("utf-8")).hexdigest()


class AuditLog:
    """Append-only JSONL audit trail.

    One file per UTC day by default (audit/audit-YYYYMMDD.jsonl); appends are
    flushed + fsynced; a module-level lock keeps concurrent writers ordered.
    """

    _lock = threading.Lock()

    def __init__(self, directory: str | Path) -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)

    @property
    def path(self) -> Path:
        day = time.strftime("%Y%m%d", time.gmtime())
        return self.directory / f"audit-{day}.jsonl"

    def append(self, event: str, run_id: str, phase: str = "", **data: Any) -> dict[str, Any]:
        with AuditLog._lock:
            prev = self._tail_hash()
            entry: dict[str, Any] = {
                "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + "Z",
                "run_id": run_id,
                "phase": phase,
                "event": event,
                "data": data,
            }
            entry["prev_hash"] = prev
            entry["hash"] = entry_hash(prev, entry)
            with open(self.path, "a", encoding="utf-8") as fh:
                fh.write(canonical(entry) + "\n")
                fh.flush()
                os.fsync(fh.fileno())
            return entry

    # -- reading -----------------------------------------------------------

    def entries(self, path: Path | None = None) -> Iterator[dict[str, Any]]:
        p = path or self.path
        if not p.exists():
            return
        with open(p, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    yield json.loads(line)

    def verify_chain(self, path: Path | None = None) -> tuple[bool, str]:
        """Recompute the chain; returns (ok, detail)."""
        prev = GENESIS
        n = 0
        for entry in self.entries(path):
            n += 1
            expected = entry.pop("hash", None)
            if expected != entry_hash(prev, entry):
                return False, f"hash mismatch at entry {n}"
            prev = expected
            entry["hash"] = expected  # restore for any later reader
        return True, f"{n} entries, chain intact"

    def tail(self, n: int = 5, path: Path | None = None) -> list[dict[str, Any]]:
        items = list(self.entries(path))
        return items[-n:]

    # -- internals -----------------------------------------------------------

    def _tail_hash(self) -> str:
        if not self.path.exists():
            return GENESIS
        last: str = GENESIS
        with open(self.path, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            end = fh.tell()
            window = 4096
            buf = b""
            while end > 0:
                start = max(0, end - window)
                fh.seek(start)
                chunk = fh.read(end - start)
                end = start
                buf = chunk + buf
                if b"\n" in chunk[:-1] or start == 0:
                    break
        lines = [l for l in buf.decode("utf-8", "replace").splitlines() if l.strip()]
        if lines:
            try:
                last = json.loads(lines[-1]).get("hash", GENESIS)
            except json.JSONDecodeError:
                return GENESIS
        return last
