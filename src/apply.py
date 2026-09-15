"""Apply a board plan to the tracker — create what is new, comment on what exists — once.

The plan is a set of effects. Each one is keyed the way the n8n Idempotency check node
keys it and checked against the same store, so the app and the workflow share one
memory of what has already been applied. A key is committed only after its effect
succeeded; a failure leaves the effect free to be retried.
"""

from __future__ import annotations

import os
from datetime import date, datetime, timezone
from pathlib import Path

from .clickup import add_comment, list_url, push_context, push_one
from .client import WorkbenchError
from .idempotency import IdempotencyStore, effect_key
from .reconcile import GATE, split_by_confidence

STORE_PATH = Path(__file__).resolve().parent.parent / "state" / "processed_effects.jsonl"


def comment_body(item: dict) -> str:
    """What the comment is about — and the only thing its key is computed from."""
    return (item.get("detail") or item.get("description") or item.get("name") or "").strip()


def comment_text(item: dict, meeting_title: str, when: str) -> str:
    """The comment a matched task receives: where it came from, then what was said.

    `when` is the date of the MEETING, which the person running this supplies. It is not
    today's date, and it is not part of the key.
    """
    return f'From the meeting "{meeting_title}" ({when}):\n{comment_body(item)}'


def create_key(task: dict) -> str:
    # A null description is no description. Read it the way comment_body reads its
    # fields and the n8n Idempotency check reads it, (j.description || ''): str(None)
    # would hash the word "None" and give one effect two keys in the store they share.
    return effect_key("NEW", "", f"{task.get('name', '')} {task.get('description') or ''}".strip())


def comment_key(item: dict) -> str:
    """Keyed on the body, never on the rendered comment.

    The rendered text carries the meeting title and date, so hashing it would hand the
    same effect a fresh key on a different day and comment twice. It would also disagree
    with the n8n Idempotency check node, which hashes the item body alone — and two
    stores that compute different keys for one effect are not one store, which is the
    whole reason both write to this file.
    """
    return effect_key("UPDATE", item.get("target_id", ""), comment_body(item))


def as_effects(decisions: list, decided: list, threshold: float = GATE) -> tuple:
    """One (create, comment, ask) plan over both kinds of decision.

    A reconciled task carries `decision` NEW/UPDATE; a reconciled meeting decision carries
    `effect` comment/ask and structurally cannot be a create. Two shapes, the same three
    outcomes — so each item is stamped with `intent` and the caller stops caring which
    kind it was. Without this the plan tab showed decisions as comments and the button
    never sent them.
    """
    create, comment, ask = split_by_confidence(decisions, threshold)
    for d in create:
        d["intent"] = "create"
    for d in comment:
        d["intent"] = "comment"
    for d in ask:
        d["intent"] = "create" if d.get("decision") == "NEW" else (
            "comment" if d.get("target_id") else "")

    for d in decided:
        # A decision comments on work that exists, or goes to a human. Never a new task.
        d["intent"] = "comment" if d.get("target_id") else ""
        if d.get("effect") == "comment" and d.get("confidence", 0) >= threshold and d["intent"]:
            comment.append(d)
        else:
            ask.append(d)
    return create, comment, ask


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def apply_plan(
    create: list[dict],
    comment: list[dict],
    list_id: str | None = None,
    store: IdempotencyStore | None = None,
    meeting_title: str = "",
    when: str | None = None,
) -> dict:
    """Create every `create` item and comment on every `comment` item, each at most once."""
    list_id = list_id or os.environ.get("CLICKUP_LIST_ID")
    if not list_id:
        raise WorkbenchError("No target list. Set CLICKUP_LIST_ID in your .env or pick a list.")
    if not create and not comment:
        raise WorkbenchError("The plan has nothing to apply.")
    store = store or IdempotencyStore(STORE_PATH)
    # The caller passes the meeting's date. Today is only the fallback for a caller that
    # has none — and it never reaches the key, so the fallback cannot cause a second
    # comment tomorrow.
    when = when or date.today().isoformat()
    # The plan was reconciled against exactly one list, list_id, so every create is
    # written there — never to a second, separately-configured backlog list. Discard the
    # backlog id from push_context; a backlog-destined task still gets its "backlog" tag
    # from push_one, it just never leaves the list this run belongs to.
    members, aliases, _backlog_id = push_context()

    summary = {
        "created": 0, "commented": 0, "skipped": 0, "assigned": 0, "backlog": 0,
        "failed": [], "total": len(create) + len(comment), "list_url": list_url(list_id),
    }

    for task in create:
        key = create_key(task)
        if store.is_duplicate(key):
            summary["skipped"] += 1
            continue
        store.mark_seen(key)
        res = push_one(task, list_id, members, aliases, None)
        if res["ok"]:
            store.commit(key, {"kind": "NEW", "target": None,
                               "preview": task.get("name", "")[:60], "ts": _now(), "source": "app"})
            summary["created"] += 1
            summary["assigned"] += res["assigned"]
            summary["backlog"] += res["backlog"]
        else:
            summary["failed"].append(res["info"])

    for item in comment:
        text = comment_text(item, meeting_title, when)
        key = comment_key(item)
        if store.is_duplicate(key):
            summary["skipped"] += 1
            continue
        store.mark_seen(key)
        ok, info = add_comment(item["target_id"], text)
        if ok:
            store.commit(key, {"kind": "UPDATE", "target": item["target_id"],
                               "preview": item.get("name", "")[:60], "ts": _now(), "source": "app"})
            summary["commented"] += 1
        else:
            summary["failed"].append(info)

    return summary
