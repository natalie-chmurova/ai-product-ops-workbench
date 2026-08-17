#!/usr/bin/env python3
"""Extraction eval: how completely does the pipeline turn a meeting into tasks?

Runs the production pipeline (extract -> tasks) N times over every labeled
transcript, then uses an LLM judge to match extracted tasks against the ground
truth for that transcript.

Every `evals/ground_truth*.json` file is one labeled transcript: the clean demo
transcript plus the deliberately messy ones. A benchmark that only ever scores
100% measures nothing, so the messy set exists to make the number mean something.

Metrics per run, averaged per transcript:
  recall     = matched MUST tasks / total MUST tasks   (did we catch everything real?)
  precision  = extracted tasks that match ANY ground-truth item / total extracted
               (did we avoid inventing noise?)

Usage:
  python evals/run_eval.py [runs]        run every transcript (default 3 runs each)
  python evals/run_eval.py 2 --only messy    only sets whose filename matches "messy"
  python evals/run_eval.py --dry-run     list what would run, call no API, spend nothing
Writes: evals/results.md
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

from src.artifacts import build_tasks            # noqa: E402
from src.client import ask                        # noqa: E402
from src.extract import extract_context           # noqa: E402

JUDGE_PROMPT = """You are a strict evaluation judge. Compare a list of EXTRACTED tasks
against a GROUND TRUTH list of expected tasks from the same meeting.

Two tasks match if they refer to the same piece of work, even with different wording.
One extracted task may match at most one ground-truth item and vice versa.

GROUND TRUTH (id: summary):
{gt}

EXTRACTED (index: name — description):
{ext}

Respond with EXACTLY one line per ground-truth id and one line per extracted index,
in this format and nothing else:

GT gt1: MATCHED 3
GT gt2: MISSED
...
EXT 0: MATCHES gt5
EXT 1: EXTRA
...
"""


def load_sets(only: str | None = None) -> list[dict]:
    """Every ground_truth*.json in evals/ is one labeled transcript."""
    sets = []
    for path in sorted((ROOT / "evals").glob("ground_truth*.json")):
        if only and only.lower() not in path.name.lower():
            continue
        gt = json.loads(path.read_text(encoding="utf-8"))
        transcript_path = ROOT / gt["transcript"]
        if not transcript_path.exists():
            raise SystemExit(f"missing transcript {gt['transcript']} referenced by {path.name}")
        sets.append(
            dict(
                name=path.name,
                label=gt.get("label", "clean"),
                gt=gt,
                transcript=transcript_path.read_text(encoding="utf-8"),
                transcript_path=gt["transcript"],
                must_ids=[t["id"] for t in gt["tasks"] if t["must"]],
            )
        )
    return sets


def run_pipeline(transcript: str) -> list[dict]:
    context = extract_context(transcript)
    return build_tasks(context)


def judge(gt: dict, tasks: list[dict]) -> tuple[dict, dict]:
    gt_lines = "\n".join(f"{t['id']}: {t['summary']}" for t in gt["tasks"])
    ext_lines = "\n".join(
        f"{i}: {t.get('name','')} — {str(t.get('description',''))[:200]}"
        for i, t in enumerate(tasks)
    )
    reply = ask(
        "You are a precise, terse evaluation judge.",
        JUDGE_PROMPT.format(gt=gt_lines, ext=ext_lines),
        max_tokens=1500,
    )
    gt_status: dict[str, bool] = {}
    ext_status: dict[int, bool] = {}
    for line in reply.splitlines():
        m = re.match(r"GT\s+(gt\d+):\s*(MATCHED|MISSED)", line.strip(), re.I)
        if m:
            gt_status[m.group(1)] = m.group(2).upper() == "MATCHED"
        m = re.match(r"EXT\s+(\d+):\s*(MATCHES|EXTRA)", line.strip(), re.I)
        if m:
            ext_status[int(m.group(1))] = m.group(2).upper() == "MATCHES"
    return gt_status, ext_status


def eval_set(s: dict, runs: int) -> list[dict]:
    rows = []
    for r in range(1, runs + 1):
        print(f"  run {r}/{runs}: extracting...", flush=True)
        tasks = run_pipeline(s["transcript"])
        gt_status, ext_status = judge(s["gt"], tasks)
        matched_must = sum(1 for i in s["must_ids"] if gt_status.get(i))
        recall = matched_must / len(s["must_ids"]) if s["must_ids"] else 1.0
        matched_ext = sum(1 for ok in ext_status.values() if ok)
        precision = matched_ext / len(tasks) if tasks else 0.0
        missed = [i for i in s["must_ids"] if not gt_status.get(i)]
        rows.append(
            dict(run=r, tasks=len(tasks), recall=recall, precision=precision, missed=missed)
        )
        print(
            f"    tasks={len(tasks)}  recall={recall:.0%}  precision={precision:.0%}"
            + (f"  missed={','.join(missed)}" if missed else "")
        )
    return rows


def main() -> None:
    args = sys.argv[1:]
    dry_run = "--dry-run" in args
    only = None
    for a in args:
        if a.startswith("--only"):
            only = a.split("=", 1)[1] if "=" in a else args[args.index(a) + 1]
    runs = next((int(a) for a in args if a.isdigit()), 3)

    sets = load_sets(only)
    if not sets:
        raise SystemExit("no ground_truth*.json found")

    if dry_run:
        print(f"DRY RUN — no API calls, nothing spent. {runs} run(s) each:\n")
        for s in sets:
            gt = s["gt"]
            debatable = len(gt["tasks"]) - len(s["must_ids"])
            words = len(s["transcript"].split())
            print(f"  {s['name']}")
            print(f"    label      : {s['label']}")
            print(f"    transcript : {s['transcript_path']} ({words} words)")
            print(f"    ground truth: {len(s['must_ids'])} must + {debatable} debatable")
            if gt.get("status"):
                print(f"    status     : {gt['status']}")
            print()
        print(f"total pipeline runs that would execute: {len(sets) * runs}")
        return

    results = []
    for s in sets:
        print(f"\n=== {s['label']} ({s['transcript_path']}) ===")
        rows = eval_set(s, runs)
        avg_r = sum(x["recall"] for x in rows) / len(rows)
        avg_p = sum(x["precision"] for x in rows) / len(rows)
        print(f"  AVG: recall={avg_r:.0%}  precision={avg_p:.0%}")
        results.append(dict(set=s, rows=rows, avg_r=avg_r, avg_p=avg_p))

    lines = [
        f"# Extraction eval — {date.today().isoformat()}",
        "",
        "Pipeline: `extract_context` → `build_tasks` · judge: LLM-as-judge (Claude) · "
        f"{runs} runs per transcript.",
        "",
        "Recall is measured over MUST items only; debatable items never penalize recall "
        "but do protect precision. The messy transcripts exist so the benchmark can fail: "
        "a number that is always 100% measures nothing.",
        "",
        "## Summary",
        "",
        "| transcript | must / debatable | recall | precision |",
        "|---|---|---|---|",
    ]
    for res in results:
        s = res["set"]
        debatable = len(s["gt"]["tasks"]) - len(s["must_ids"])
        lines.append(
            f"| {s['label']} | {len(s['must_ids'])} / {debatable} | "
            f"{res['avg_r']:.0%} | {res['avg_p']:.0%} |"
        )

    for res in results:
        s = res["set"]
        lines += [
            "",
            f"## {s['label']}",
            "",
            f"`{s['transcript_path']}` · ground truth `evals/{s['name']}`",
            "",
            "| run | tasks extracted | recall (must) | precision | missed |",
            "|---|---|---|---|---|",
        ]
        for x in res["rows"]:
            lines.append(
                f"| {x['run']} | {x['tasks']} | {x['recall']:.0%} | {x['precision']:.0%} | "
                f"{', '.join(x['missed']) or '—'} |"
            )
        lines += ["", f"**Average: recall {res['avg_r']:.0%} · precision {res['avg_p']:.0%}**"]

    lines.append("")
    (ROOT / "evals" / "results.md").write_text("\n".join(lines), encoding="utf-8")
    print("\nwritten: evals/results.md")


if __name__ == "__main__":
    main()
