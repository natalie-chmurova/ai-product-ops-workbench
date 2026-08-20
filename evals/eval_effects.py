#!/usr/bin/env python3
"""Effect eval: given a board, what does the pipeline decide to DO with each point?

The extraction eval asks whether the work was found. This asks the next question —
create it, comment on what already exists, or ask a human — which is the half of the
SOP that could not be measured while every transcript reconciled against the same
unrelated board.

It deliberately does NOT run extraction. Points come straight from the validated
ground truth, so an extraction miss and a routing miss stay separate numbers; folded
together they would hide which one to fix.

Five effects are scored:
  create · comment · ask · verify_deadline · verify_status

The last two have no implementation. They will score 0% until WB-9 and WB-18 land,
which is the point of measuring them now.

An `ask` counts as correct only when it came from honest doubt. An escalation caused
by an unreadable reply or a target absent from the board is a guardrail firing —
crediting it would report a broken run as a good one.

Usage:
  python evals/eval_effects.py               every labeled transcript
  python evals/eval_effects.py --only messy  only sets whose filename matches
  python evals/eval_effects.py --only ground_truth.json --board evals/board_demo_live_snapshot.json
                                             override the fixture (the clutter measurement)
  python evals/eval_effects.py --dry-run     list what would run, call no API
Writes: evals/effect_results.md
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(dotenv_path=ROOT / ".env")

from src.clickup import load_board_fixture  # noqa: E402
from src.reconcile import reconcile, split_by_confidence  # noqa: E402

EFFECTS = ("create", "comment", "ask", "verify_deadline", "verify_status")
UNIMPLEMENTED = ("verify_deadline", "verify_status")


def load_sets(only: str | None = None) -> list[dict]:
    """Every ground_truth*.json that names a board is one labeled transcript."""
    sets = []
    for path in sorted((ROOT / "evals").glob("ground_truth*.json")):
        if path.name == "match_ground_truth.json":
            continue
        if only and only.lower() not in path.name.lower():
            continue
        gt = json.loads(path.read_text(encoding="utf-8"))
        if not gt.get("board"):
            print(f"  skipping {path.name}: no board reference")
            continue
        entries = []
        for e in gt.get("tasks", []) + gt.get("manager_notes", []):
            if not e.get("expected_effect"):
                continue
            entries.append(
                {
                    "id": e.get("id") or e.get("item", "")[:40],
                    "name": e.get("summary") or e.get("item", ""),
                    "detail": e.get("manager_note") or e.get("verdict", ""),
                    "expected_effect": e["expected_effect"],
                    "expected_target": e.get("expected_target", ""),
                    "flagged": bool(e.get("review_note")),
                }
            )
        sets.append(
            dict(
                name=path.name,
                label=gt.get("label", "clean"),
                board_ref=gt["board"],
                labels_status=gt.get("labels_status", ""),
                entries=entries,
            )
        )
    return sets


def decide_all(entries: list[dict], board: list[dict]) -> list[dict]:
    """Route every point through the real reconciler and flatten to one effect each."""
    points = [{"what": e["name"], "context": e["detail"]} for e in entries]
    decisions = reconcile(points, board)
    create, comment, ask = split_by_confidence(decisions)
    effect_of = {id(d): "create" for d in create}
    effect_of.update({id(d): "comment" for d in comment})
    effect_of.update({id(d): "ask" for d in ask})

    out = []
    for entry, d in zip(entries, decisions):
        out.append(
            {
                "id": entry["id"],
                "effect": effect_of[id(d)],
                "target_id": d.get("target_id", ""),
                "confidence": d.get("confidence", 0.0),
                "escalation_cause": d.get("escalation_cause", ""),
                "decision": d.get("decision", ""),
                "reason": d.get("reason", ""),
            }
        )
    return out


def score(entries: list[dict], decided: list[dict]) -> dict:
    """Compare intended effects with chosen ones. Pure — no API, no files."""
    by_id = {d["id"]: d for d in decided}
    per_effect = {e: {"total": 0, "correct": 0} for e in EFFECTS}
    by_cause: dict[str, int] = {}
    effect_correct = 0
    target_total = 0
    target_correct = 0
    misses = []

    for entry in entries:
        expected = entry["expected_effect"]
        got = by_id.get(entry["id"], {})
        chosen = got.get("effect", "")
        cause = got.get("escalation_cause", "")
        per_effect[expected]["total"] += 1

        if chosen == "ask":
            key = cause or "low_confidence"
            by_cause[key] = by_cause.get(key, 0) + 1

        # An escalation caused by a guardrail is the mechanism failing safe, not the
        # agent correctly asking for help. Only honest doubt earns the credit.
        ok = chosen == expected
        if expected == "ask" and ok and cause not in ("", "low_confidence"):
            ok = False

        if ok:
            effect_correct += 1
            per_effect[expected]["correct"] += 1
        else:
            misses.append(
                {
                    "id": entry["id"],
                    "expected": expected,
                    "got": chosen or "(nothing)",
                    "cause": cause,
                    "intent": f"{got.get('decision','')} {got.get('target_id','') or 'NONE'}".strip(),
                    "reason": got.get("reason", ""),
                    "flagged": entry.get("flagged", False),
                }
            )

        if entry.get("expected_target"):
            target_total += 1
            if got.get("target_id") == entry["expected_target"]:
                target_correct += 1

    return {
        "total": len(entries),
        "effect_correct": effect_correct,
        "target_total": target_total,
        "target_correct": target_correct,
        "per_effect": per_effect,
        "by_cause": by_cause,
        "misses": misses,
    }


def report(results: list[dict], board_override: str | None) -> str:
    # Whether the labels are signed off is a fact about the ground truth, so read it
    # from there. The hardcoded "DRAFT" that used to live here went stale the moment
    # Natallia signed them off, and the next run would have silently overwritten her
    # note with it again.
    statuses = sorted({r["set"]["labels_status"] for r in results if r["set"]["labels_status"]})
    status_line = (
        "**Label status:** " + "; ".join(statuses) + "."
        if statuses
        else "**The effect labels are DRAFT** and have not been validated."
    )
    lines = [
        f"# Effect eval (what the pipeline decides to DO) — {date.today().isoformat()}",
        "",
        "Points come from the validated ground truth, not from extraction: an extraction "
        "miss and a routing miss are different defects and are kept as different numbers.",
        "",
        "`verify_deadline` and `verify_status` have no implementation yet (WB-9, WB-18). "
        "They are measured anyway, and score zero, so the fix has something to move.",
        "",
        "An `ask` counts as correct only when it came from honest doubt. An escalation "
        "caused by an unreadable reply or a target absent from the board is a guardrail "
        "firing, and crediting it would report a broken run as a good one.",
        "",
        status_line + " Rows marked ⚑ are ones the fixtures forced a judgement on; "
        "they carry a `review_note` in the ground truth.",
        "",
    ]
    if board_override:
        lines += [f"**Board overridden for this run:** `{board_override}`", ""]

    lines += [
        "## Summary",
        "",
        "| transcript | board | points | effect accuracy | target accuracy |",
        "|---|---|---|---|---|",
    ]
    for r in results:
        s, sc = r["set"], r["score"]
        acc = sc["effect_correct"] / sc["total"] if sc["total"] else 0.0
        tacc = sc["target_correct"] / sc["target_total"] if sc["target_total"] else None
        lines.append(
            f"| {s['label']} | `{r['board_ref']}` | {sc['total']} | {acc:.0%} | "
            + (f"{tacc:.0%} |" if tacc is not None else "— |")
        )

    for r in results:
        s, sc = r["set"], r["score"]
        lines += ["", f"## {s['label']}", "", "| expected effect | points | correct |", "|---|---|---|"]
        for effect in EFFECTS:
            row = sc["per_effect"][effect]
            if not row["total"]:
                continue
            note = " _(not implemented)_" if effect in UNIMPLEMENTED else ""
            lines.append(f"| `{effect}`{note} | {row['total']} | {row['correct']} |")
        if sc["by_cause"]:
            lines += [
                "",
                "Escalations by cause: "
                + ", ".join(f"`{k}` {v}" for k, v in sorted(sc["by_cause"].items())),
            ]
        if sc["misses"]:
            lines += ["", "| point | expected | got | cause | agent's intent |", "|---|---|---|---|---|"]
            for m in sc["misses"]:
                flag = " ⚑" if m["flagged"] else ""
                lines.append(
                    f"| {m['id']}{flag} | `{m['expected']}` | `{m['got']}` | "
                    f"{m['cause'] or '—'} | {m['intent'] or '—'} |"
                )
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    args = sys.argv[1:]
    dry_run = "--dry-run" in args
    only = None
    board_override = None
    for i, a in enumerate(args):
        if a.startswith("--only"):
            only = a.split("=", 1)[1] if "=" in a else args[i + 1]
        if a.startswith("--board"):
            board_override = a.split("=", 1)[1] if "=" in a else args[i + 1]

    sets = load_sets(only)
    if not sets:
        raise SystemExit("no ground_truth*.json with a board reference found")

    if dry_run:
        print("DRY RUN — no API calls, nothing spent.\n")
        for s in sets:
            board = load_board_fixture(board_override or s["board_ref"])
            wanted: dict[str, int] = {}
            for e in s["entries"]:
                wanted[e["expected_effect"]] = wanted.get(e["expected_effect"], 0) + 1
            flagged = sum(1 for e in s["entries"] if e["flagged"])
            print(f"  {s['name']} ({s['label']})")
            print(f"    board  : {board_override or s['board_ref']} ({len(board)} tasks)")
            print(f"    points : {len(s['entries'])} ({flagged} flagged for review)")
            print(f"    expects: {', '.join(f'{k} {v}' for k, v in sorted(wanted.items()))}")
            print()
        print(f"model calls that would run: {sum(len(s['entries']) for s in sets)}")
        return

    results = []
    for s in sets:
        board = load_board_fixture(board_override or s["board_ref"])
        print(f"\n=== {s['label']} · board {board_override or s['board_ref']} ({len(board)} tasks) ===")
        decided = decide_all(s["entries"], board)
        sc = score(s["entries"], decided)
        acc = sc["effect_correct"] / sc["total"] if sc["total"] else 0.0
        print(f"  effect accuracy {acc:.0%} ({sc['effect_correct']}/{sc['total']})")
        if sc["by_cause"]:
            print(f"  escalations: {sc['by_cause']}")
        results.append(dict(set=s, score=sc, board_ref=board_override or s["board_ref"]))

    (ROOT / "evals" / "effect_results.md").write_text(report(results, board_override), encoding="utf-8")
    print("\nwritten: evals/effect_results.md")


if __name__ == "__main__":
    main()
