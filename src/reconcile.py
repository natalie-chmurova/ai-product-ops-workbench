"""Stage 1.5 — reconcile meeting points against the live board.

The extraction stage reads a transcript in isolation, so everything it finds
looks new. A delivery manager never works that way: the first question is
always "is this already on the board?". Without asking it, a decision becomes
a task, and work someone is already doing becomes a duplicate of itself.

This is the same job the n8n board-sync workflow does, brought into the Python
pipeline so both paths reason the same way. The prompt lives in
`prompts/match.md` — one source shared by this module, the n8n Match agent node
and the decision eval, so the three cannot drift apart.
"""

from __future__ import annotations

import re

from .client import ask, load_prompt


def board_summary(tasks: list[dict]) -> str:
    """The board as the agent sees it: one `id | name` per line."""
    return "\n".join(f"{t['id']} | {t.get('name', '')}" for t in tasks)


def parse_decision(reply: str, board: list[dict]) -> dict:
    """Parse the agent's four-line answer, defensively.

    A malformed reply defaults to NEW with zero confidence rather than raising:
    an unparseable answer is exactly the case a human should look at, not one
    that should stop the run.
    """
    decision = (re.search(r"DECISION:\s*(NEW|UPDATE)", reply, re.I) or [None, "NEW"])[1].upper()
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
    if decision == "UPDATE" and not target:
        confidence = 0.0

    if not re.search(r"DECISION:\s*(NEW|UPDATE)", reply, re.I):
        confidence = 0.0

    return {
        "decision": decision,
        "target_id": target,
        "confidence": confidence,
        "reason": reason,
    }


def split_by_confidence(decisions: list[dict], threshold: float = 0.8) -> tuple:
    """Route decisions into (create, comment, ask_a_human).

    The same confidence gate the n8n workflow uses: confident calls are applied,
    doubtful ones are escalated rather than guessed.
    """
    create, comment, ask = [], [], []
    for d in decisions:
        if d.get("confidence", 0) < threshold:
            ask.append(d)
        elif d.get("decision") == "UPDATE":
            comment.append(d)
        else:
            create.append(d)
    return create, comment, ask


def plan_markdown(decisions: list[dict], board: list[dict], threshold: float = 0.8) -> str:
    """What the run intends to do to the board, before it does any of it."""
    names = {t["id"]: t.get("name", "") for t in board}
    create, comment, ask = split_by_confidence(decisions, threshold)

    lines = ["# Board plan", ""]
    if not board:
        lines += ["The board has no open tasks, so every point is new by definition.", ""]
    else:
        lines += [f"Reconciled against {len(board)} open tasks on the board.", ""]

    lines += [f"## Create ({len(create)})", ""]
    for d in create:
        lines.append(f"- **{d.get('name','')}** — {d.get('reason','')}")
    if not create:
        lines.append("- nothing")

    lines += ["", f"## Comment on existing ({len(comment)})", ""]
    for d in comment:
        target = names.get(d.get("target_id", ""), d.get("target_id", ""))
        lines.append(f"- **{d.get('name','')}** → `{target}` — {d.get('reason','')}")
    if not comment:
        lines.append("- nothing")

    lines += ["", f"## Ask a human ({len(ask)})", ""]
    for d in ask:
        lines.append(
            f"- **{d.get('name','')}** (confidence {d.get('confidence',0):.2f}) — {d.get('reason','')}"
        )
    if not ask:
        lines.append("- nothing")

    lines.append("")
    return "\n".join(lines)


def decide_one(name: str, detail: str, board: list[dict]) -> dict:
    """Ask the agent whether one meeting point is new work or an update."""
    prompt = load_prompt("match").format(
        board=board_summary(board), name=name, detail=detail
    )
    reply = ask("You are a precise board-sync agent.", prompt, max_tokens=400)
    return parse_decision(reply, board)


def reconcile(items: list[dict], board: list[dict]) -> list[dict]:
    """Decide new-vs-update for every extracted item.

    Returns each item enriched with the decision, so the caller can create,
    comment, or escalate. With an empty board every item is new by definition —
    no call is made, and nothing is invented.
    """
    out = []
    for item in items:
        name = item.get("name") or item.get("what") or ""
        detail = item.get("description") or item.get("context") or ""
        if board:
            decision = decide_one(name, detail, board)
        else:
            decision = {
                "decision": "NEW",
                "target_id": "",
                "confidence": 1.0,
                "reason": "board is empty, nothing to match against",
            }
        # normalise the label: stage 1 calls it `what`, tasks call it `name`,
        # and everything downstream (plan, comments) needs one predictable field
        out.append({**item, **decision, "name": name, "detail": detail})
    return out
