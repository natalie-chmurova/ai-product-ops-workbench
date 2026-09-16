#!/usr/bin/env python3
"""AI Product Ops Workbench — command-line entry point.

Turn a raw meeting transcript into product-ops artifacts:

    python workbench.py samples/transcript_demo.txt

Outputs (written to ./outputs/):
    context.json         the structured understanding (stage 1)
    tasks.json           ClickUp-ready tasks
    sprint_summary.md    stakeholder sprint summary
    bug_triage.md        bug triage table
    speaker_summary.md   per-person breakdown (status, commitments, blockers)
    report.html          a single page showing input -> output
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from src.artifacts import (
    build_bug_triage,
    build_speaker_summary,
    build_sprint_summary,
    build_tasks,
)
from src.assignees import roster_line
from src.client import WorkbenchError
from src.clickup import get_tasks, load_board_fixture, team_roster
from src.plan import MEETING_DECISION, build_plan, plan_markdown
from src.reconcile import reconcile, reconcile_decisions
from src.extract import extract_context
from src.render import render_report
from src.transcribe import is_audio, transcribe_audio

load_dotenv()  # read ANTHROPIC_API_KEY from a local .env if present

OUTPUT_DIR = Path(__file__).resolve().parent / "outputs"


def _write(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    print(f"  wrote {path.relative_to(Path.cwd())}" if _under_cwd(path) else f"  wrote {path}")


def _under_cwd(path: Path) -> bool:
    try:
        path.relative_to(Path.cwd())
        return True
    except ValueError:
        return False


def run(transcript_path: Path, board_path: Path | None = None) -> None:
    if not transcript_path.exists():
        raise WorkbenchError(f"File not found: {transcript_path}")

    # The board is read before any model call — a fixture path that is mistyped and a
    # token that has expired are both mistakes in the setup, and finding either after
    # two stages of extraction means paying for a run that was never going to finish.
    board = load_board_fixture(board_path) if board_path else get_tasks()
    # Computed once, here, and reused at the reconcile stage below — a board fixture
    # path and a configured CLICKUP_LIST_ID both count as "configured"; get_tasks()
    # and load_board_fixture() both represent "configured but empty" the same way a
    # missing configuration is represented ([]), so this is the one place that still
    # knows the difference.
    board_configured = bool(board_path) or bool(os.environ.get("CLICKUP_LIST_ID"))
    if board_path:
        print(f"Board: fixture {board_path} ({len(board)} tasks)")
    elif not board_configured:
        print("Board: none configured — every point will count as new")
    else:
        # A configured list that is empty is not the same fact as no list at all, and
        # get_tasks returns [] for both. The caller knows which, because it knows
        # whether a list was configured; say the one that is true.
        print(f"Board: live ClickUp list ({len(board)} open tasks)"
              + ("" if board else " — empty, so every point counts as new"))

    if is_audio(transcript_path):
        print("Stage 0/3  Transcribing audio (local, no upload)...")
        transcript = transcribe_audio(transcript_path)
    else:
        transcript = transcript_path.read_text(encoding="utf-8")
    OUTPUT_DIR.mkdir(exist_ok=True)

    roster = team_roster()
    if roster:
        print(f"Team roster ({len(roster)}): {roster_line(roster)}")

    print("Stage 1/3  Understanding the transcript...")
    context = extract_context(transcript, roster)
    _write(OUTPUT_DIR / "context.json", json.dumps(context, ensure_ascii=False, indent=2))

    print("Stage 2/3  Building artifacts (tasks, sprint summary, bug triage, per-speaker)...")
    tasks = build_tasks(context)
    sprint_md = build_sprint_summary(context)
    triage_md = build_bug_triage(context)
    speakers_md = build_speaker_summary(context, transcript, roster)
    _write(OUTPUT_DIR / "tasks.json", json.dumps(tasks, ensure_ascii=False, indent=2))
    _write(OUTPUT_DIR / "sprint_summary.md", sprint_md)
    _write(OUTPUT_DIR / "bug_triage.md", triage_md)
    _write(OUTPUT_DIR / "speaker_summary.md", speakers_md)

    # The live board is the default on purpose: the demo's worth is that it talks to
    # a real tracker. A fixture is how an eval transcript gets a board from its own
    # world, and it is always asked for explicitly.
    #
    # board_plan.md is written on every run — with a board, with an empty one, and with
    # none — so the file never goes on describing an earlier meeting's plan.
    if board or board_configured:
        if board:
            print(f"Stage 2.5/3  Reconciling against the board ({len(board)} open tasks)...")
        else:
            # board is [] here but a fixture or list *was* configured — "not configured"
            # would be false, and the earlier "Board: ... empty" line would otherwise be
            # contradicted a few lines later.
            print("Stage 2.5/3  Board configured but empty — every point counts as new.")
        # The plan is about what would be created, and what gets created is a task —
        # so reconcile the ClickUp-ready list, not the raw action items. This also puts
        # extracted bugs through the board check, which the action items never did.
        # An empty board costs no model call: every point is new without asking.
        # One plan, built once: the file below and the counts printed after it are the
        # same value read twice, so they cannot disagree about the same run. The CLI
        # writes to no tracker, so its plan names no scope -- and a board it did read,
        # empty or not, is still a board it read.
        plan = build_plan(
            reconcile(tasks, board),
            reconcile_decisions(context.get("decisions", []), board),
            board,
            "",
        )
        _write(OUTPUT_DIR / "board_plan.md", plan_markdown(plan))
        counts = plan.counts
        print(f"  create {counts['create']} · comment on existing {counts['comment']}"
              f" · ask a human {counts['ask']}")
        print(f"  decisions: {len(plan.from_source(MEETING_DECISION))} "
              "(comment on existing work, never new tasks)")
    else:
        print("Stage 2.5/3  No board configured — every point counts as new.")
        _write(OUTPUT_DIR / "board_plan.md",
               "No board was read for this run (no ClickUp list or board fixture configured), "
               "so nothing was reconciled.\n")

    print("Stage 3/3  Rendering the report page...")
    report_html = render_report(transcript, tasks, sprint_md, triage_md, speakers_md)
    _write(OUTPUT_DIR / "report.html", report_html)

    print(f"\nDone. {len(tasks)} tasks generated.")
    print(f"Open the report:  {OUTPUT_DIR / 'report.html'}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Turn a meeting transcript (or audio recording) into product-ops artifacts.")
    parser.add_argument("transcript", type=Path, help="Path to a transcript .txt or an audio file (.m4a/.mp3/.wav/...)")
    parser.add_argument(
        "--board",
        type=Path,
        default=None,
        help="Reconcile against a board fixture file instead of the live ClickUp list",
    )
    args = parser.parse_args()
    try:
        run(args.transcript, args.board)
    except (WorkbenchError, ValueError) as exc:
        print(f"\nError: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
