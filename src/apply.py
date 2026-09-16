"""Apply a plan to the tracker — create what is new, comment on what exists — once.

The plan is a set of effects, built by `src/plan.py` and carrying the one list it was
reconciled against. Each effect is keyed the way the n8n Idempotency check node keys it
and checked against the same store, so the app and the workflow share one memory of what
has already been applied. A key is committed only after its effect succeeded; a failure
leaves the effect free to be retried.
"""

from __future__ import annotations

from datetime import date

from .clickup import add_comment, list_url, push_context, push_one
from .client import WorkbenchError
from .idempotency import (
    ALREADY_APPLIED,
    APPLIED,
    FAILED,
    Attempt,
    IdempotencyStore,
    comment_body,
    comment_key,
    create_key,
)
from .plan import Plan

# Which side of the shared store wrote a record. The n8n workflow writes "sync" into the
# same file; this is the app.
SOURCE = "app"


def comment_text(point: dict, meeting_title: str, when: str) -> str:
    """The comment a matched task receives: where it came from, then what was said.

    `when` is the date of the MEETING, which the person running this supplies. It is not
    today's date, and it is not part of the key.
    """
    return f'From the meeting "{meeting_title}" ({when}):\n{comment_body(point)}'


def _count_unapplied(summary: dict, attempt: Attempt) -> None:
    """An effect that never ran, counted as the reason it did not.

    A repeat is not an "already applied": nothing had seen it before this click, and
    telling a person it had sends them looking on the board for work that was
    never written.
    """
    summary["already_applied" if attempt.outcome == ALREADY_APPLIED else "repeated"] += 1


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
    # Where the store keeps its records is the store's own business, and it is the
    # file n8n appends to; a path derived here, from this module's location, was a
    # second answer to that question.
    store = store or IdempotencyStore()
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
        "created": 0, "commented": 0, "already_applied": 0, "repeated": 0,
        "assigned": 0, "backlog": 0, "failed": [], "total": len(create) + len(comment),
        "list_url": list_url(plan.scope),
    }

    for effect in create:
        # The store runs the effect, so the order — reserve, write, record — is its
        # own; here there is only the writing and the counting.
        attempt = store.apply_once(
            create_key(effect.point),
            lambda e=effect: _push(e, plan.scope, members, aliases),
            kind="NEW", target=None, preview=effect.name, source=SOURCE)
        if attempt.outcome == APPLIED:
            summary["created"] += 1
            summary["assigned"] += attempt.info["assigned"]
            summary["backlog"] += attempt.info["backlog"]
        elif attempt.outcome == FAILED:
            summary["failed"].append(attempt.info["info"])
        else:
            _count_unapplied(summary, attempt)

    for effect in comment:
        text = comment_text(effect.point, meeting_title, when)
        attempt = store.apply_once(
            comment_key(effect.point),
            lambda e=effect, t=text: add_comment(e.target_id, t),
            kind="UPDATE", target=effect.target_id, preview=effect.name, source=SOURCE)
        if attempt.outcome == APPLIED:
            summary["commented"] += 1
        elif attempt.outcome == FAILED:
            summary["failed"].append(attempt.info)
        else:
            _count_unapplied(summary, attempt)

    return summary


def _push(effect, scope: str, members: list, aliases: dict) -> tuple:
    """Create one task, and report it the way every effect reports itself: (ok, info)."""
    res = push_one(effect.point, scope, members, aliases, None)
    return res["ok"], res
