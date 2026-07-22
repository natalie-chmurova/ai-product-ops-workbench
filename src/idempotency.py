#!/usr/bin/env python3
"""Idempotency for the meeting -> ClickUp sync.

Deterministic guard so re-processing the same meeting does not create
duplicate tasks or comments. Keyed on the *applied effect* (an UPDATE comment
on a task, or a NEW task), computed after the Match agent's decision.

The key spec is mirrored byte-for-byte in the n8n "Idempotency check" and
"Mark processed" Code nodes; tests/idempotency_vectors.json pins the parity.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path


def normalize(text: str) -> str:
    """Lowercase, collapse any whitespace run to one space, then trim."""
    return re.sub(r"\s+", " ", (text or "").lower()).strip()


def effect_key(kind: str, target: str, content: str) -> str:
    """SHA-1 hex of the effect payload. kind is "UPDATE" or "NEW".

    UPDATE: "UPDATE|<target_task_id>|<normalized comment>"
    NEW:    "NEW|<normalized title + ' ' + description>"
    """
    if kind == "UPDATE":
        payload = f"UPDATE|{target}|{normalize(content)}"
    else:
        payload = f"NEW|{normalize(content)}"
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


class IdempotencyStore:
    """Append-only JSONL store of applied-effect keys.

        store = IdempotencyStore(Path("state/processed_effects.jsonl"))
        key = effect_key("UPDATE", target_id, comment)
        if store.is_duplicate(key):
            skip()
        else:
            store.mark_seen(key)   # reserve before applying (in-batch dedup)
            apply_effect()         # the side effect
            store.commit(key, {...})  # record only after success
    """

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._committed: set = set()
        self._seen_this_run: set = set()
        if self.path.exists():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    self._committed.add(json.loads(line)["key"])
                except (json.JSONDecodeError, KeyError):
                    continue  # tolerate a bad line, never crash the run

    def is_duplicate(self, key: str) -> bool:
        return key in self._committed or key in self._seen_this_run

    def mark_seen(self, key: str) -> None:
        self._seen_this_run.add(key)

    def commit(self, key: str, meta: dict) -> None:
        """Append the key record. Call ONLY after a successful effect."""
        self._committed.add(key)
        self._seen_this_run.discard(key)
        record = {"key": key, **meta}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
