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

The raw decisions are kept in `evals/effect_decisions.json`. The model call is the
expensive half of this harness and the confidence gate is the cheap one, so questions
about where the gate belongs are answered by re-reading that file rather than by paying
for another run.

Usage:
  python evals/eval_effects.py               every labeled transcript
  python evals/eval_effects.py --only messy  only sets whose filename matches
  python evals/eval_effects.py --only ground_truth.json --board evals/board_demo_live_snapshot.json
                                             override the fixture (the clutter measurement)
  python evals/eval_effects.py --dry-run     list what would run, call no API
  python evals/eval_effects.py --replay      re-score saved decisions, call no API
  python evals/eval_effects.py --replay --threshold 0.7
                                             the same decisions at a different gate
  python evals/eval_effects.py --sweep       accuracy across gates 0.50-0.95, call no API
Writes: evals/effect_results.md, evals/effect_decisions.json
        evals/threshold_sweep.md (--sweep)
"""

from __future__ import annotations

import copy
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
DECISIONS_PATH = ROOT / "evals" / "effect_decisions.json"
SWEEP_PATH = ROOT / "evals" / "threshold_sweep.md"
GATE = 0.8


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


def decide_raw(entries: list[dict], board: list[dict]) -> list[dict]:
    """Route every point through the real reconciler. One model call per point."""
    points = [{"what": e["name"], "context": e["detail"]} for e in entries]
    return reconcile(points, board)


def effects_from(entries: list[dict], decisions: list[dict], threshold: float = GATE) -> list[dict]:
    """Flatten raw decisions to one effect each, at a given confidence gate.

    Pure and free. The model call is the expensive half of this harness and the gate is
    the cheap one, which is why the raw decisions are kept rather than discarded after
    scoring: asking where the threshold should sit is then a re-read, not another run.
    """
    decisions = copy.deepcopy(decisions)
    # split_by_confidence stamps "low_confidence" on whatever falls below the gate, so a
    # replay at a different threshold has to clear the previous pass's stamp first. A
    # cause a guardrail set — an unreadable reply, a target absent from the board — is a
    # fact about the reply rather than about the gate, and survives.
    for d in decisions:
        if d.get("escalation_cause") == "low_confidence":
            d["escalation_cause"] = ""

    create, comment, ask = split_by_confidence(decisions, threshold)
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


def save_decisions(raw: dict) -> None:
    """Persist what the agent actually said, so calibration costs nothing to re-ask."""
    DECISIONS_PATH.write_text(
        json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    n = sum(len(v["decisions"]) for v in raw.values())
    print(f"written: evals/{DECISIONS_PATH.name} ({n} raw decisions)")


def load_decisions() -> dict:
    if not DECISIONS_PATH.exists():
        raise SystemExit(
            f"no saved decisions at evals/{DECISIONS_PATH.name} — run the eval once "
            "without --replay/--sweep to populate it"
        )
    return json.loads(DECISIONS_PATH.read_text(encoding="utf-8"))


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


def sweep_report(sets: list[dict], cache: dict, thresholds: list[float]) -> str:
    """Effect accuracy as a function of the confidence gate, from saved decisions.

    Costs nothing: every row re-reads the same replies at a different threshold.
    """
    lines = [
        f"# Threshold sweep — {date.today().isoformat()}",
        "",
        "Effect accuracy as a function of the confidence gate, recomputed from the saved "
        f"decisions in `evals/{DECISIONS_PATH.name}`. No model was called: every row is the "
        "same set of replies scored at a different threshold.",
        "",
        "**This cannot tell you where to set the gate.** It is scored against the same "
        "labels it would be tuned on, and there is no held-out set — the best row here is "
        "an upper bound on what a threshold can buy, not a validated setting. What it is "
        "good for is the shape: whether accuracy is flat (the gate is not the problem) or "
        "peaked (it is).",
        "",
        f"Current gate: **{GATE}**.",
        "",
    ]
    header = "| gate | " + " | ".join(s["label"].split(" — ")[0] for s in sets) + " | overall | escalations |"
    lines += [header, "|" + "---|" * (len(sets) + 3)]

    for t in thresholds:
        cells, correct, total, escalated = [], 0, 0, 0
        for s in sets:
            decided = effects_from(s["entries"], cache[s["name"]]["decisions"], t)
            sc = score(s["entries"], decided)
            cells.append(f"{sc['effect_correct'] / sc['total']:.0%}" if sc["total"] else "—")
            correct += sc["effect_correct"]
            total += sc["total"]
            escalated += sum(1 for d in decided if d["effect"] == "ask")
        mark = " ←" if abs(t - GATE) < 1e-9 else ""
        lines.append(
            f"| {t:.2f}{mark} | " + " | ".join(cells) + f" | **{correct / total:.0%}** | {escalated} |"
        )

    lines += [
        "",
        "Read the escalation column beside the accuracy one. A lower gate buys accuracy by "
        "sending fewer points to a human, which is only a gain if the extra calls it lets "
        "through are right. Where accuracy climbs and escalations fall together, the gate "
        "was costing correct actions; where accuracy climbs only as escalations collapse, "
        "the gate is doing its job and the number is flattering itself.",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    args = sys.argv[1:]
    dry_run = "--dry-run" in args
    sweep = "--sweep" in args
    replay = "--replay" in args or sweep
    only = None
    board_override = None
    threshold = GATE
    for i, a in enumerate(args):
        if a.startswith("--only"):
            only = a.split("=", 1)[1] if "=" in a else args[i + 1]
        if a.startswith("--board"):
            board_override = a.split("=", 1)[1] if "=" in a else args[i + 1]
        if a.startswith("--threshold"):
            threshold = float(a.split("=", 1)[1] if "=" in a else args[i + 1])

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

    cache = load_decisions() if replay else {}
    if replay:
        missing = [s["name"] for s in sets if s["name"] not in cache]
        if missing:
            raise SystemExit(
                f"no saved decisions for {', '.join(missing)} — run without "
                "--replay/--sweep to populate them"
            )

    if sweep:
        thresholds = [round(0.50 + 0.05 * i, 2) for i in range(10)]
        SWEEP_PATH.write_text(sweep_report(sets, cache, thresholds), encoding="utf-8")
        print(f"replayed {sum(len(s['entries']) for s in sets)} decisions at "
              f"{len(thresholds)} thresholds — no API calls, nothing spent.")
        print(f"written: evals/{SWEEP_PATH.name}")
        return

    results = []
    raw: dict[str, dict] = {}
    for s in sets:
        board_ref = board_override or s["board_ref"]
        board = load_board_fixture(board_ref)
        print(f"\n=== {s['label']} · board {board_ref} ({len(board)} tasks) ===")
        if replay:
            decisions = cache[s["name"]]["decisions"]
            print(f"  replaying {len(decisions)} saved decisions at gate {threshold}")
        else:
            decisions = decide_raw(s["entries"], board)
        raw[s["name"]] = dict(board=board_ref, decisions=decisions)

        decided = effects_from(s["entries"], decisions, threshold)
        sc = score(s["entries"], decided)
        acc = sc["effect_correct"] / sc["total"] if sc["total"] else 0.0
        print(f"  effect accuracy {acc:.0%} ({sc['effect_correct']}/{sc['total']})")
        if sc["by_cause"]:
            print(f"  escalations: {sc['by_cause']}")
        results.append(dict(set=s, score=sc, board_ref=board_ref))

    # Only a real run earns the right to overwrite the record. A replay is an
    # experiment on decisions already made, and must not restate them as new ones.
    if not replay:
        save_decisions(raw)
        (ROOT / "evals" / "effect_results.md").write_text(
            report(results, board_override), encoding="utf-8"
        )
        print("\nwritten: evals/effect_results.md")
    else:
        print("\nreplay only — effect_results.md left untouched.")


if __name__ == "__main__":
    main()
