#!/usr/bin/env python3
"""AI Product Ops Workbench — command-line entry point.

Turn a raw meeting transcript into product-ops artifacts:

    python workbench.py samples/transcript_demo.txt

Outputs (written to ./outputs/):
    context.json         the structured understanding (stage 1)
    tasks.json           ClickUp-ready tasks
    sprint_summary.md    stakeholder sprint summary
    bug_triage.md        bug triage table
    report.html          a single page showing input -> output
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

from src.artifacts import build_bug_triage, build_sprint_summary, build_tasks
from src.client import WorkbenchError
from src.extract import extract_context
from src.render import render_report

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


def run(transcript_path: Path) -> None:
    if not transcript_path.exists():
        raise WorkbenchError(f"Transcript file not found: {transcript_path}")

    transcript = transcript_path.read_text(encoding="utf-8")
    OUTPUT_DIR.mkdir(exist_ok=True)

    print("Stage 1/3  Understanding the transcript...")
    context = extract_context(transcript)
    _write(OUTPUT_DIR / "context.json", json.dumps(context, ensure_ascii=False, indent=2))

    print("Stage 2/3  Building artifacts (tasks, sprint summary, bug triage)...")
    tasks = build_tasks(context)
    sprint_md = build_sprint_summary(context)
    triage_md = build_bug_triage(context)
    _write(OUTPUT_DIR / "tasks.json", json.dumps(tasks, ensure_ascii=False, indent=2))
    _write(OUTPUT_DIR / "sprint_summary.md", sprint_md)
    _write(OUTPUT_DIR / "bug_triage.md", triage_md)

    print("Stage 3/3  Rendering the report page...")
    report_html = render_report(transcript, tasks, sprint_md, triage_md)
    _write(OUTPUT_DIR / "report.html", report_html)

    print(f"\nDone. {len(tasks)} tasks generated.")
    print(f"Open the report:  {OUTPUT_DIR / 'report.html'}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Turn a meeting transcript into product-ops artifacts.")
    parser.add_argument("transcript", type=Path, help="Path to a transcript .txt file")
    args = parser.parse_args()
    try:
        run(args.transcript)
    except (WorkbenchError, ValueError) as exc:
        print(f"\nError: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
