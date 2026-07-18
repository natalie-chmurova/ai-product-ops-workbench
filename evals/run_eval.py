#!/usr/bin/env python3
"""Extraction eval: how completely does the pipeline turn the meeting into tasks?

Runs the production pipeline (extract -> tasks) N times over the demo transcript,
then uses an LLM judge to match extracted tasks against a labeled ground truth.

Metrics per run, averaged at the end:
  recall     = matched MUST tasks / total MUST tasks   (did we catch everything real?)
  precision  = extracted tasks that match ANY ground-truth item / total extracted
               (did we avoid inventing noise?)

Usage:  python evals/run_eval.py [runs]     (default 3)
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

GT = json.loads((ROOT / "evals" / "ground_truth.json").read_text(encoding="utf-8"))
TRANSCRIPT = (ROOT / GT["transcript"]).read_text(encoding="utf-8")

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


def run_pipeline() -> list[dict]:
    context = extract_context(TRANSCRIPT)
    return build_tasks(context)


def judge(tasks: list[dict]) -> tuple[dict, dict]:
    gt_lines = "\n".join(f"{t['id']}: {t['summary']}" for t in GT["tasks"])
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


def main() -> None:
    runs = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    must_ids = [t["id"] for t in GT["tasks"] if t["must"]]
    rows = []
    for r in range(1, runs + 1):
        print(f"run {r}/{runs}: extracting...", flush=True)
        tasks = run_pipeline()
        gt_status, ext_status = judge(tasks)
        matched_must = sum(1 for i in must_ids if gt_status.get(i))
        recall = matched_must / len(must_ids)
        matched_ext = sum(1 for ok in ext_status.values() if ok)
        precision = matched_ext / len(tasks) if tasks else 0.0
        missed = [i for i in must_ids if not gt_status.get(i)]
        rows.append(
            dict(run=r, tasks=len(tasks), recall=recall, precision=precision, missed=missed)
        )
        print(
            f"  tasks={len(tasks)}  recall={recall:.0%}  precision={precision:.0%}"
            + (f"  missed={','.join(missed)}" if missed else "")
        )

    avg_r = sum(x["recall"] for x in rows) / len(rows)
    avg_p = sum(x["precision"] for x in rows) / len(rows)
    print(f"\nAVG over {runs} runs:  recall={avg_r:.0%}  precision={avg_p:.0%}")

    lines = [
        f"# Extraction eval — {date.today().isoformat()}",
        "",
        f"Pipeline: `extract_context` → `build_tasks` · judge: LLM-as-judge (Claude) · "
        f"ground truth: {len(must_ids)} must + "
        f"{len(GT['tasks']) - len(must_ids)} debatable tasks",
        "",
        "| run | tasks extracted | recall (must) | precision | missed |",
        "|---|---|---|---|---|",
    ]
    for x in rows:
        lines.append(
            f"| {x['run']} | {x['tasks']} | {x['recall']:.0%} | {x['precision']:.0%} | "
            f"{', '.join(x['missed']) or '—'} |"
        )
    lines += ["", f"**Average: recall {avg_r:.0%} · precision {avg_p:.0%}**", ""]
    (ROOT / "evals" / "results.md").write_text("\n".join(lines), encoding="utf-8")
    print("written: evals/results.md")


if __name__ == "__main__":
    main()
