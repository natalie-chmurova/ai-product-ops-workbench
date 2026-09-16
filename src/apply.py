"""Apply a plan to the tracker — create what is new, comment on what exists — once.

The plan is a set of effects, built by `src/plan.py` and carrying the one list it was
reconciled against. Each effect is keyed the way the n8n Idempotency check node keys it
and checked against the same store, so the app and the workflow share one memory of what
has already been applied. A key is committed only after its effect succeeded; a failure
leaves the effect free to be retried.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

from .clickup import add_comment, list_url, push_context, push_one
from .client import WorkbenchError
from .idempotency import IdempotencyStore, comment_body, comment_key, create_key
from .plan import Plan

STORE_PATH = Path(__file__).resolve().parent.parent / "state" / "processed_effects.jsonl"


def comment_text(point: dict, meeting_title: str, when: str) -> str:
    """The comment a matched task receives: where it came from, then what was said.

    `when` is the date of the MEETING, which the person running this supplies. It is not
    today's date, and it is not part of the key.
    """
    return f'From the meeting "{meeting_title}" ({when}):\n{comment_body(point)}'


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def apply_plan(
    plan: Plan,
    approved: list = (),
    store: IdempotencyStore | None = None,
    meeting_title: str = "",
    when: str | None = None,
) -> dict:
    """Write `plan` to the list it was built against, each effect at most once.

    `approved` is the asks a person ticked; each is applied as the effect the agent
    intended, and one with no safe intent is not applied at all.
    """
    if not plan.scope:
        # No fallback to a list from the environment: a plan written to a board it was
        # never reconciled against duplicates the work already on that board.
        raise WorkbenchError(
            "This plan was built without a ClickUp list, so there is nothing to apply it "
            "to. Pick a list and generate again."
        )
    # What a ticked ask becomes is the plan's own rule; asking the plan for it keeps
    # this module to writing, and keeps one routing in one place.
    plan = plan.with_approved(approved)
    create, comment = plan.create, plan.comment
    if not create and not comment:
        raise WorkbenchError("The plan has nothing to apply.")
    store = store or IdempotencyStore(STORE_PATH)
    # The caller passes the meeting's date. Today is only the fallback for a caller that
    # has none — and it never reaches the key, so the fallback cannot cause a second
    # comment tomorrow.
    when = when or date.today().isoformat()
    # The plan was reconciled against exactly one list, so every create is written there
    # — never to a second, separately-configured backlog list. Discard the backlog id
    # from push_context; a backlog-destined task still gets its "backlog" tag from
    # push_one, it just never leaves the list this run belongs to.
    members, aliases, _backlog_id = push_context()

    summary = {
        "created": 0, "commented": 0, "skipped": 0, "assigned": 0, "backlog": 0,
        "failed": [], "total": len(create) + len(comment),
        "list_url": list_url(plan.scope),
    }

    for effect in create:
        key = create_key(effect.point)
        if store.is_duplicate(key):
            summary["skipped"] += 1
            continue
        store.mark_seen(key)
        res = push_one(effect.point, plan.scope, members, aliases, None)
        if res["ok"]:
            store.commit(key, {"kind": "NEW", "target": None,
                               "preview": effect.name[:60], "ts": _now(), "source": "app"})
            summary["created"] += 1
            summary["assigned"] += res["assigned"]
            summary["backlog"] += res["backlog"]
        else:
            summary["failed"].append(res["info"])

    for effect in comment:
        text = comment_text(effect.point, meeting_title, when)
        key = comment_key(effect.point)
        if store.is_duplicate(key):
            summary["skipped"] += 1
            continue
        store.mark_seen(key)
        ok, info = add_comment(effect.target_id, text)
        if ok:
            store.commit(key, {"kind": "UPDATE", "target": effect.target_id,
                               "preview": effect.name[:60], "ts": _now(), "source": "app"})
            summary["commented"] += 1
        else:
            summary["failed"].append(info)

    return summary
