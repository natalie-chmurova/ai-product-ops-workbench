#!/usr/bin/env python3
"""Idempotency for the meeting -> ClickUp sync: the key of an effect, and the store.

Deterministic guard so re-processing the same meeting does not create
duplicate tasks or comments. Keyed on the *applied effect* (an UPDATE comment
on a task, or a NEW task), computed after the Match agent's decision.

This one module answers "what is this effect's key": which text a point contributes (its
name and body, by name_and_body, which reconcile.py reads points with too), how that text
is normalised and hashed, and the key of creating a task or of commenting on one. The n8n
"Idempotency check" Code node computes the same key from the items "Parse decision"
builds; tests/test_n8n_parity.py runs that node's own code to check that the two agree,
and tests/idempotency_vectors.json pins the formula.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path


# Whitespace as JavaScript's \s defines it, which is also what String.prototype.trim()
# strips: the n8n Idempotency check normalises with it, and Parse decision trims the
# comment body with it. Python's own \s and str.strip() differ on six characters -- they
# take U+001C-U+001F and U+0085 and leave U+FEFF out -- so a text holding one of those
# would key differently on the two sides of one store. The node is deployed live and
# changing it means a re-import, so its definition wins.
_WHITESPACE = "".join(map(chr, (
    0x09, 0x0A, 0x0B, 0x0C, 0x0D, 0x20,    # tab, LF, VT, FF, CR, space
    0xA0, 0x1680, *range(0x2000, 0x200B),  # no-break, ogham and U+2000-U+200A spaces
    0x2028, 0x2029,                        # line and paragraph separators
    0x202F, 0x205F, 0x3000,                # narrow no-break, math and ideographic spaces
    0xFEFF,                                # zero width no-break space (byte order mark)
)))
_WHITESPACE_RUN = re.compile(f"[{re.escape(_WHITESPACE)}]+")


def _trim(text: str) -> str:
    """Strip both ends as JavaScript's trim() does."""
    return text.strip(_WHITESPACE)


def normalize(text: str) -> str:
    """Lowercase, collapse any whitespace run to one space, then trim -- whitespace as the
    n8n node's JavaScript defines it.

    The whitespace half is pinned against the node; the lowercasing half is Python's own,
    and the two agree only as far as their Unicode versions do. 95 code points assigned
    after Python 3.9's Unicode 13 -- U+1C89, U+2C2F, U+A7C0-U+A7DC, Vithkuqi, Garay,
    U+16EA0-U+16EB8 -- fold in the node and stay put here, so a text holding one of them
    keys differently on the two sides. That is a known limit, not an oversight: a
    hand-kept case table would have to track whichever node version the live n8n runs,
    and meeting text does not contain those scripts. The letters that do agree (Ae, I-dot,
    Sigma among them) are pinned by tests/test_n8n_parity.py against the node itself.
    """
    return _trim(_WHITESPACE_RUN.sub(" ", (text or "").lower()))


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


def name_and_body(point: dict) -> tuple[str, str]:
    """A point's name and its body: the text its match is asked about, and the only text
    its key is made from. One definition, for every shape a point comes in.

    The name is `name`, or `what` as extraction writes it. The body is what the point says
    beyond its name: `detail` once reconcile() has handed the point on, `description` on a
    task, `context` on an action item. A meeting decision, the only point that names the
    work it `affects`, is one sentence, and that sentence is its body as well as its name.
    That is a rule, not a fallback, so a field given to meeting decisions later cannot
    become their body and re-key the comments already applied for them. A field that is
    missing or null reads as empty, as the n8n node's (x || '') reads it; str(None) would
    hash the word "None" and give one effect two keys in the store the app and n8n share.
    """
    name = point.get("name") or point.get("what") or ""
    if "affects" in point:
        return name, name
    return name, point.get("detail") or point.get("description") or point.get("context") or ""


def comment_body(point: dict) -> str:
    """What a comment says about a point — and the only text its key is computed from: its
    body, or its name when it has none, trimmed as Parse decision's
    (item.description || item.name || '').trim() trims it."""
    name, body = name_and_body(point)
    return _trim(body or name)


def create_key(point: dict) -> str:
    """The key of creating a point as a new task: its name and its body, joined as the
    Idempotency check node joins (j.name || '') and (j.description || ''). There is no
    strip here: normalize trims, with the node's whitespace."""
    name, body = name_and_body(point)
    return effect_key("NEW", "", f"{name} {body}")


def comment_key(point: dict) -> str:
    """The key of commenting on `point`'s target task: keyed on the body, never on the
    rendered comment.

    The rendered text carries the meeting title and date, so hashing it would hand the
    same effect a fresh key on a different day and comment twice. It would also disagree
    with the n8n Idempotency check node, which hashes the item body alone — and two
    stores that compute different keys for one effect are not one store, which is the
    whole reason both write to state/processed_effects.jsonl.
    """
    return effect_key("UPDATE", point.get("target_id", ""), comment_body(point))


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


def effects_from_log(path: Path) -> list:
    """Read evals/decision_log.jsonl into (kind, target, content) effects.

    Uses the logged `point` as the content — enough to demonstrate the
    deterministic guard without any API call.
    """
    effects = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        d = json.loads(line)
        if d.get("decision") == "UPDATE":
            effects.append(("UPDATE", d.get("target") or "", d.get("point") or ""))
        else:
            effects.append(("NEW", "", d.get("point") or ""))
    return effects


def apply_batch(effects: list, store: IdempotencyStore) -> tuple:
    """Mark-then-apply, mirroring the n8n check -> filter -> apply -> mark order.

    Phase 1 marks fresh effects (in-batch dedup); phase 2 "applies" them (no
    real side effect here) and commits the key only after that apply.
    """
    fresh = []
    skipped = 0
    for kind, target, content in effects:
        key = effect_key(kind, target, content)
        if store.is_duplicate(key):
            skipped += 1
        else:
            store.mark_seen(key)
            fresh.append((key, kind, target, content))
    applied = 0
    for key, kind, target, content in fresh:
        store.commit(key, {"kind": kind, "target": target or None, "preview": content[:60]})
        applied += 1
    return applied, skipped


def _demo() -> None:
    import tempfile

    root = Path(__file__).resolve().parent.parent
    effects = effects_from_log(root / "evals" / "decision_log.jsonl")
    with tempfile.TemporaryDirectory() as d:
        store = IdempotencyStore(Path(d) / "demo.jsonl")
        a1, s1 = apply_batch(effects, store)
        a2, s2 = apply_batch(effects, store)
    print(f"effects in the meeting: {len(effects)}")
    print(f"run 1:  applied={a1}  skipped={s1}")
    print(f"run 2:  applied={a2}  skipped={s2}")
    print(f"\nIdempotent: the second run applied {a2} new effects "
          f"(re-processing the same meeting is a no-op).")


if __name__ == "__main__":
    _demo()
