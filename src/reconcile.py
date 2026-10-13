"""Stage 1.5 — reconcile meeting points against the live board.

The extraction stage reads a transcript in isolation, so everything it finds
looks new. A delivery manager never works that way: the first question is
always "is this already on the board?". Without asking it, a decision becomes
a task, and work someone is already doing becomes a duplicate of itself.

This is the same job the n8n board-sync workflow does, brought into the Python
pipeline so both paths reason the same way. The prompt lives in
`prompts/match.md` — one source shared by this module, the n8n Match agent node
and the decision eval, so the three cannot drift apart.

The answer this module produces is a **match**, in `CONTEXT.md`'s sense: new work,
or an update to a named board row, with a confidence and a reason. It is not a
meeting decision (a call a person made) and not a verdict (a call a person makes on
what the agent asked about). The `DECISION:` line the model writes, and the
`"decision"` field a match carries, are the wire format — pinned against the n8n
Parse decision node — not the name of the idea.
"""

from __future__ import annotations

import re

from .client import ask, load_prompt
from .idempotency import name_and_body


def board_summary(tasks: list[dict]) -> str:
    """The board as the agent sees it: id, name, and whatever else the task carries.

    Status, owner and deadline are read from the tracker already — they were simply
    dropped before the agent ever saw them. That is why "they said it's done" and
    "that date slipped" had nothing to reason against: the agent cannot check a
    status it was never shown.

    Empty fields are omitted rather than rendered as "none", so a sparse board stays
    readable and a board carrying only id and name renders exactly as it used to.
    """
    lines = []
    for t in tasks:
        parts = [f"{t.get('id', '')} | {t.get('name', '')}"]
        if t.get("status"):
            parts.append(f"status: {t['status']}")
        owners = ", ".join(a for a in t.get("assignees", []) if a)
        if owners:
            parts.append(f"owner: {owners}")
        if t.get("due_date"):
            parts.append(f"due: {t['due_date']}")
        lines.append(" | ".join(parts))
    return "\n".join(lines)


def parse_match(reply: str, board: list[dict]) -> dict:
    """Parse the agent's four-line answer into one match, defensively.

    A malformed reply defaults to NEW with zero confidence rather than raising:
    an unparseable answer is exactly the case a human should look at, not one
    that should stop the run.

    The two ways this can go wrong are reported as `escalation_cause`, because an
    escalation caused by a guardrail firing is a different event from one where the
    agent reached an answer and doubted it — and counted as the same, a broken run
    scores as a good one.
    """
    # The match's own call, NEW or UPDATE. `DECISION:` is what the model writes and
    # `"decision"` is what the record carries; both are the format, kept byte for byte.
    new_or_update = (re.search(r"DECISION:\s*(NEW|UPDATE)", reply, re.I) or [None, "NEW"])[1].upper()
    target = (re.search(r"TASK_ID:\s*([A-Za-z0-9]+)", reply, re.I) or [None, ""])[1]
    raw_conf = (re.search(r"CONFIDENCE:\s*([\d.]+)", reply, re.I) or [None, "0"])[1]
    reason = ((re.search(r"REASON:\s*(.+)", reply, re.I) or [None, ""])[1]).strip()

    try:
        confidence = float(raw_conf)
    except ValueError:
        confidence = 0.0

    board_ids = {t["id"] for t in board}
    if target.upper() == "NONE" or target not in board_ids:
        target = ""

    # An UPDATE that names no real task is not trustworthy — same guardrail the
    # n8n workflow applies, so it drops to a human instead of writing anywhere.
    if new_or_update == "UPDATE" and not target:
        confidence = 0.0

    unparseable = not re.search(r"DECISION:\s*(NEW|UPDATE)", reply, re.I)
    if unparseable:
        confidence = 0.0

    # An escalation caused by a guardrail firing is not the same event as an agent
    # that reached an answer and honestly doubted it. Scored as one, a broken run
    # reads as a good one — so the two failures this function can see are named.
    if unparseable:
        cause = "unreadable"
    elif new_or_update == "UPDATE" and not target:
        cause = "phantom_target"
    else:
        cause = ""

    # Escalating without saying why wastes the human's time — they see a question
    # and no reason for it. Always hand over something readable.
    if not reason:
        if unparseable:
            reason = "could not read the agent's answer, so this needs a human"
        elif new_or_update == "UPDATE" and not target:
            reason = "matched an existing task that is not on the board"
        else:
            reason = "the agent gave no reason"

    return {
        # Pinned: the field every stored match record, the decision log and the n8n
        # Parse decision node spell this way.
        "decision": new_or_update,
        "target_id": target,
        "confidence": confidence,
        "reason": reason,
        "escalation_cause": cause,
    }


def reconcile_meeting_decisions(meeting_decisions: list[dict],
                                board: list[dict]) -> list[dict]:
    """Match each meeting decision to the work it changes.

    A meeting decision is never new work — "ship Wednesday, cut payments" changes an
    existing commitment. So the only useful outcomes are: comment on the task it
    affects, or ask a human because no task on the board obviously matches.
    Creating something is not on the menu.
    """
    out = []
    for meeting_decision in meeting_decisions:
        # A bare string is a meeting decision given as its sentence alone.
        meeting_decision = (meeting_decision if isinstance(meeting_decision, dict)
                            else {"what": str(meeting_decision)})
        name, _ = name_and_body(meeting_decision)  # its sentence, also its body
        affects = meeting_decision.get("affects", "")

        if board:
            # "This decision changes: ..." is prompt text a model reads, not a name.
            match = match_one(name, f"This decision changes: {affects}", board)
        else:
            match = {"decision": "NEW", "target_id": "", "confidence": 0.0,
                     "reason": "no board to match this meeting decision against"}

        # NEW is meaningless here: if nothing matched, a human looks at it.
        effect = "comment" if match["target_id"] else "ask"
        out.append({
            "name": name,
            "affects": affects,
            # The meeting decision's own kind — what it changed — carried through under
            # the key the extraction writes. Not an effect kind; see `src/plan.py`.
            "kind": meeting_decision.get("kind", "other"),
            "effect": effect,
            "target_id": match["target_id"],
            "confidence": match["confidence"],
            "reason": match["reason"],
        })
    return out


def match_one(name: str, detail: str, board: list[dict]) -> dict:
    """Ask the agent whether one meeting point is new work or an update."""
    prompt = load_prompt("match").format(
        board=board_summary(board), name=name, detail=detail
    )
    # Room for the model's thinking as well as the four-line answer: the two share this
    # ceiling, and at 400 the thinking sometimes spent it before DECISION: was written.
    reply = ask("You are a precise board-sync agent.", prompt, max_tokens=4000)
    return parse_match(reply, board)


def reconcile(items: list[dict], board: list[dict]) -> list[dict]:
    """Match every extracted item against the board: new work, or an update.

    Returns each item enriched with its match, so the caller can create, comment, or
    escalate. With an empty board every item is new by definition — no call is made,
    and nothing is invented.
    """
    out = []
    for item in items:
        name, detail = name_and_body(item)
        if board:
            match = match_one(name, detail, board)
        else:
            match = {
                "decision": "NEW",
                "target_id": "",
                "confidence": 1.0,
                "reason": "board is empty, nothing to match against",
            }
        # normalise the label: stage 1 calls it `what`, tasks call it `name`, and
        # everything downstream (plan, comments, the key) needs one predictable pair,
        # read by the same definition the key reads a point with
        out.append({**item, **match, "name": name, "detail": detail})
    return out
