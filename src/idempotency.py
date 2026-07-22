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
import re


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
