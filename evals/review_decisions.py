#!/usr/bin/env python3
"""Weekly decision review — the feedback loop for the board-sync agent.

The n8n workflow logs every agent decision (what it decided, how confident, and
whether it auto-executed or was escalated to a human) to evals/decision_log.jsonl.
This script turns that raw log into a short review: what the agent did, where it
was unsure, and which decisions a human should look at to tune the SOP prompt.

Run it after a batch of meetings (or "weekly"): the human-gated, low-confidence
decisions are exactly the examples worth adding to the eval set and fixing.

Usage:  python evals/review_decisions.py
Writes: evals/decision_review.md
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "evals" / "decision_log.jsonl"


def load() -> list[dict]:
    if not LOG.exists():
        return []
    rows = []
    for line in LOG.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def main() -> None:
    rows = load()
    if not rows:
        print("No decisions logged yet. Run the workflow first.")
        return

    total = len(rows)
    auto = [r for r in rows if r.get("gate") == "auto"]
    human = [r for r in rows if r.get("gate") == "human"]
    dec = Counter(r.get("decision") for r in rows)
    confs = [r.get("confidence", 0) for r in rows]
    avg_conf = sum(confs) / len(confs)

    out = [
        f"# Agent decision review — {date.today().isoformat()}",
        "",
        f"**{total} decisions logged** · {len(auto)} auto-executed "
        f"({len(auto)/total:.0%}) · {len(human)} escalated to a human "
        f"({len(human)/total:.0%})",
        "",
        f"By type: {dec.get('UPDATE', 0)} update · {dec.get('NEW', 0)} new · "
        f"average confidence {avg_conf:.2f}",
        "",
        "## Decisions a human should review",
        "",
        "_Escalated (low-confidence) calls — the examples worth adding to the eval "
        "set and tuning the SOP against._",
        "",
    ]
    review = sorted(human, key=lambda r: r.get("confidence", 0))
    if not review:
        out.append("_None this batch — every decision cleared the confidence gate._")
    else:
        out.append("| confidence | decision | point | why the agent was unsure |")
        out.append("|---|---|---|---|")
        for r in review:
            out.append(
                f"| {r.get('confidence'):.2f} | {r.get('decision')} | "
                f"{r.get('point','')} | {r.get('reason','')} |"
            )
    out.append("")
    (ROOT / "evals" / "decision_review.md").write_text("\n".join(out), encoding="utf-8")

    print(f"{total} decisions · {len(auto)} auto · {len(human)} to review")
    print("written: evals/decision_review.md")


if __name__ == "__main__":
    main()
