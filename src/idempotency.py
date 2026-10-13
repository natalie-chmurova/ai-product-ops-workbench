#!/usr/bin/env python3
"""Idempotency for the meeting -> ClickUp sync: the key of an effect, and the store.

Deterministic guard so re-processing the same meeting does not create
duplicate tasks or comments. Keyed on the *applied effect* (an UPDATE comment
on a task, or a NEW task), computed after the Match agent's answer.

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
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .client import WorkbenchError


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


# What came of running one effect. Four outcomes, and they are four because the three
# they replaced hid two facts: an effect that failed was reported as skipped, and an
# effect repeated inside one run as one the store had seen before that run.
APPLIED = "applied"
ALREADY_APPLIED = "already applied"   # the key was in the store before this run
REPEATED = "repeated"                 # an identical effect earlier in this run
FAILED = "failed"

OUTCOMES = (APPLIED, ALREADY_APPLIED, REPEATED, FAILED)


@dataclass(frozen=True)
class Attempt:
    """What one effect came to: which of the four outcomes, and what the effect itself
    reported — nothing, when it was not run."""

    outcome: str
    info: object = None


def _now() -> str:
    """The moment a record is written, as the n8n Mark processed node's
    new Date().toISOString() writes it."""
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


_CHECKOUT = Path(__file__).resolve().parent.parent


def store_path() -> Path:
    """The file the app and the n8n workflow both append to, and both read.

    WB_HOME when it is set, this checkout otherwise. Under a WB_HOME the two sides name
    one file without either being told which: the nodes join `base + '/state/...'` where
    this joins path segments, and the results name one file. Where the rules differ is
    without a WB_HOME -- the nodes refuse to run, because n8n is started outside any
    checkout and has nothing to fall back to, while this side has the checkout it is
    running from. Read when a store is opened, not at import, so a run that sets
    WB_HOME is obeyed.

    A relative WB_HOME is refused. String-joined or segment-joined, it resolves against
    the working directory of whichever process reads it, and n8n's is not the app's --
    so both sides would go on working and quietly keep two stores. That is exactly the
    failure this rule exists to remove: the app used to derive the path from the
    location of the module doing the applying, and two checkouts -- or a packaged
    install -- then kept two stores, in which every effect one had applied came back as
    new in the other.
    """
    home = os.environ.get("WB_HOME")
    if home and not Path(home).is_absolute():
        raise WorkbenchError(
            f"WB_HOME must be an absolute path to the checkout, not {home!r}: n8n and "
            "the app resolve a relative one against their own working directories and "
            "would keep two separate stores of applied effects."
        )
    return Path(home or _CHECKOUT) / "state" / "processed_effects.jsonl"


class IdempotencyStore:
    """Append-only JSONL store of applied-effect keys, and the one operation that runs an
    effect against it.

        store = IdempotencyStore()          # the file the n8n nodes append to as well
        attempt = store.apply_once(comment_key(point),
                                   lambda: add_comment(point["target_id"], text),
                                   kind="UPDATE", target=point["target_id"],
                                   preview=point["name"], source="app")

    `apply_once` owns the order the whole guard rests on — reserve the key, run the
    effect, record it only if it succeeded — so that no caller writes that order out
    again. It was three calls and a docstring saying what order to make them in; both
    loops of `apply_plan` and the published demo wrote the order out by hand, and a
    failed effect kept its reservation for the rest of the run, so an identical effect
    after it was reported as already applied although nothing had been written.
    """

    def __init__(self, path: Path | None = None) -> None:
        # A caller with no file in mind gets the one this checkout shares with n8n; a
        # test gets its own. Nobody has to know where the shared one is.
        self.path = Path(path) if path is not None else store_path()
        # Three sets, because the outcomes are three different facts: what the file held
        # before this run, what this run has written, and what it is running right now.
        self._before: set = self._keys_on_file()
        self._applied: set = set()
        self._reserved: set = set()

    def apply_once(self, key: str, effect: Callable[[], tuple], *, kind: str,
                   target: str | None, preview: str, source: str) -> Attempt:
        """Run `effect` unless this key has been applied already, and record it if it
        succeeds.

        `effect` takes no arguments and answers the way a write to the tracker answers:
        `(ok, info)`. On ok the record is appended and the key is the store's from then
        on; on not-ok nothing is written and the key is free again — in this run and the
        next — so a failed effect is retried rather than looking applied. An effect that
        raises frees its key too and the error goes on to the caller: this store guards
        against applying an effect twice, not against the tracker falling over.
        """
        if key in self._before:
            return Attempt(ALREADY_APPLIED)
        if key in self._reserved or key in self._applied:
            return Attempt(REPEATED)
        self._reserved.add(key)
        try:
            ok, info = effect()
        finally:
            # Reserved only while it runs: a key still held by an effect that failed --
            # or raised -- would report an identical effect after it as a repeat, and
            # nothing would ever retry it.
            self._reserved.discard(key)
        if not ok:
            return Attempt(FAILED, info)
        self._applied.add(key)
        self._append(key, kind=kind, target=target, preview=preview, source=source)
        return Attempt(APPLIED, info)

    def _keys_on_file(self) -> set:
        keys = set()
        if not self.path.exists():
            return keys
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                keys.add(json.loads(line)["key"])
            except (json.JSONDecodeError, KeyError):
                continue  # tolerate a bad line, never crash the run
        return keys

    def _append(self, key: str, *, kind: str, target: str | None, preview: str,
                source: str) -> None:
        """One line per applied effect, in the format the n8n Mark processed node writes.

        Both sides append to this file and both sides read it, so the record is composed
        here rather than at each call site: a caller says what the effect was and who it
        was, and the key, the timestamp and the cut of the preview are the store's.
        """
        record = {"key": key, "kind": kind, "target": target or None,
                  "preview": (preview or "")[:60], "ts": _now(), "source": source}
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


def apply_batch(effects: list, store: IdempotencyStore) -> dict:
    """Run every effect through the store once, and count how each of them went.

    There is no real side effect here — this is the no-API demo — so each effect simply
    reports success. What is being demonstrated is the store's order, and this asks for
    it by the one operation rather than writing it out a third time.
    """
    counts = {outcome: 0 for outcome in OUTCOMES}
    for kind, target, content in effects:
        attempt = store.apply_once(
            effect_key(kind, target, content), lambda: (True, None),
            kind=kind, target=target, preview=content, source="demo")
        counts[attempt.outcome] += 1
    return counts


def _demo() -> None:
    import tempfile

    root = Path(__file__).resolve().parent.parent
    effects = effects_from_log(root / "evals" / "decision_log.jsonl")
    with tempfile.TemporaryDirectory() as d:
        # Two runs, two stores over one file: the second run knows what the first applied
        # because it reads the records, which is how a second click — or n8n after the
        # app — finds out too.
        path = Path(d) / "demo.jsonl"
        first = apply_batch(effects, IdempotencyStore(path))
        second = apply_batch(effects, IdempotencyStore(path))
    print(f"effects in the meeting: {len(effects)}")
    for label, counts in (("run 1", first), ("run 2", second)):
        print(f"{label}:  " + "  ".join(f"{o}={counts[o]}" for o in OUTCOMES))
    print(f"\nIdempotent: the second run applied {second[APPLIED]} new effects "
          f"(re-processing the same meeting is a no-op).")


if __name__ == "__main__":
    _demo()
