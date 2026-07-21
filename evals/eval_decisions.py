#!/usr/bin/env python3
"""Agent-decision eval: is the board-sync agent's NEW-vs-UPDATE call correct?

This evaluates the *agentic decision* at the heart of the board-sync workflow —
not just whether tasks were extracted, but whether the agent correctly decides
that a meeting point is new work vs. an update to an existing task, and (for
updates) picks the right task.

Because the decision is categorical, it is scored by exact match against a
labeled ground truth — no LLM judge needed. Runs N times (the model is
non-deterministic) and averages.

Metrics:
  decision accuracy = correct NEW/UPDATE calls / total points
  target accuracy   = correct task id / points whose true decision is UPDATE

Usage:  python evals/eval_decisions.py [runs]     (default 3)
Writes: evals/decision_results.md
"""

from __future__ import annotations

import json
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(dotenv_path=ROOT / ".env")

from src.client import ask  # noqa: E402

GT = json.loads((ROOT / "evals" / "match_ground_truth.json").read_text(encoding="utf-8"))
BOARD_TEXT = "\n".join(f"{t['id']} | {t['name']}" for t in GT["board"])
BOARD_IDS = {t["id"] for t in GT["board"]}

# Same instruction the n8n "Match agent" node uses, kept in sync on purpose.
MATCH_PROMPT = """You are a board-sync agent. Decide whether a meeting point is NEW work or an
UPDATE to a task that already exists on the board.

EXISTING TASKS (id | name):
{board}

MEETING POINT:
Name: {name}
Detail: {detail}

Rules:
- Prefer UPDATE when the point clearly concerns the same work as an existing task, even with
  different wording.
- Use NEW only when no existing task reasonably covers it.
- If you are torn between two tasks or unsure, LOWER your confidence. Never guess silently.

Respond in EXACTLY this format (four lines, nothing else):
DECISION: <NEW|UPDATE>
TASK_ID: <existing task id or NONE>
CONFIDENCE: <0.0-1.0>
REASON: <one short sentence>
"""


def decide(point: dict) -> tuple[str, str]:
    reply = ask(
        "You are a precise board-sync agent.",
        MATCH_PROMPT.format(board=BOARD_TEXT, name=point["name"], detail=point["detail"]),
        max_tokens=400,
    )
    decision = (re.search(r"DECISION:\s*(NEW|UPDATE)", reply, re.I) or [None, "NEW"])[1].upper()
    target = (re.search(r"TASK_ID:\s*([A-Za-z0-9]+)", reply, re.I) or [None, ""])[1]
    if target.upper() == "NONE" or target not in BOARD_IDS:
        target = ""
    return decision, target


def main() -> None:
    runs = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    points = GT["points"]
    updates = [p for p in points if p["expected_decision"] == "UPDATE"]

    run_rows = []
    per_point_wrong: dict[str, int] = {}
    for r in range(1, runs + 1):
        print(f"run {r}/{runs}...", flush=True)
        dec_ok = 0
        tgt_ok = 0
        for p in points:
            decision, target = decide(p)
            d_correct = decision == p["expected_decision"]
            dec_ok += d_correct
            if p["expected_decision"] == "UPDATE":
                if d_correct and target == p["expected_target"]:
                    tgt_ok += 1
            if not d_correct or (p["expected_decision"] == "UPDATE" and target != p["expected_target"]):
                per_point_wrong[p["name"]] = per_point_wrong.get(p["name"], 0) + 1
        dec_acc = dec_ok / len(points)
        tgt_acc = tgt_ok / len(updates) if updates else 1.0
        run_rows.append((r, dec_acc, tgt_acc))
        print(f"  decision accuracy={dec_acc:.0%}  target accuracy={tgt_acc:.0%}")

    avg_d = sum(x[1] for x in run_rows) / len(run_rows)
    avg_t = sum(x[2] for x in run_rows) / len(run_rows)
    print(f"\nAVG over {runs} runs:  decision={avg_d:.0%}  target={avg_t:.0%}")

    lines = [
        f"# Agent-decision eval (board sync: new vs update) — {date.today().isoformat()}",
        "",
        f"Board: {len(GT['board'])} tasks · points: {len(points)} "
        f"({len(updates)} true updates, {len(points) - len(updates)} true new) · "
        f"scored by exact match, {runs} runs",
        "",
        "| run | decision accuracy | target accuracy (updates) |",
        "|---|---|---|",
    ]
    for r, d, t in run_rows:
        lines.append(f"| {r} | {d:.0%} | {t:.0%} |")
    lines += ["", f"**Average: decision {avg_d:.0%} · target {avg_t:.0%}**"]
    if per_point_wrong:
        lines += ["", "Points the agent got wrong at least once:"]
        for name, n in sorted(per_point_wrong.items(), key=lambda x: -x[1]):
            lines.append(f"- {name} ({n}/{runs} runs)")
    lines.append("")
    (ROOT / "evals" / "decision_results.md").write_text("\n".join(lines), encoding="utf-8")
    print("written: evals/decision_results.md")


if __name__ == "__main__":
    main()
