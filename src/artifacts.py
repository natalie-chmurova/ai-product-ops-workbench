"""Stage 2 — the "Document Builder".

Takes the structured summary from stage 1 and produces the three deliverables:
  - ClickUp-ready tasks (list of dicts)
  - a sprint summary (Markdown text)
  - a bug triage table (Markdown text)

Each one is a single, focused Claude call driven by its own prompt file.
"""

from __future__ import annotations

import json

from .assignees import roster_line
from .client import ask, ask_json, load_prompt


def _summary_as_text(context: dict) -> str:
    """The shared meeting summary, pretty-printed for the prompts to read."""
    return json.dumps(context, ensure_ascii=False, indent=2)


def build_tasks(context: dict) -> list:
    """Structured summary -> list of ClickUp-ready task dicts."""
    system_prompt = load_prompt("tasks")
    user_content = f"Here is the structured meeting summary:\n\n{_summary_as_text(context)}"
    # A full board of detailed tasks can be long, so give it generous headroom.
    tasks = ask_json(system_prompt, user_content, max_tokens=8000)
    # The prompt asks for an array; be forgiving if it comes wrapped in a key.
    if isinstance(tasks, dict):
        tasks = tasks.get("tasks", [])
    return tasks


def build_sprint_summary(context: dict) -> str:
    """Structured summary -> sprint summary Markdown."""
    system_prompt = load_prompt("sprint")
    user_content = f"Here is the structured meeting summary:\n\n{_summary_as_text(context)}"
    return ask(system_prompt, user_content, max_tokens=2000).strip()


def build_bug_triage(context: dict) -> str:
    """Structured summary -> bug triage Markdown."""
    system_prompt = load_prompt("bug_triage")
    user_content = f"Here is the structured meeting summary:\n\n{_summary_as_text(context)}"
    return ask(system_prompt, user_content, max_tokens=2000).strip()


def build_speaker_summary(context: dict, transcript: str, roster: list | None = None) -> str:
    """Per-person breakdown: status, commitments, blockers, follow-ups.

    This one also gets the raw transcript, because who said what is the whole
    point and stage 1 only keeps an `owner` per action item. Passing the
    transcript here (instead of widening the stage-1 contract) keeps the
    extraction eval measuring the same thing it measured before.

    `roster` (see `src.assignees.team_roster`) turns speaker identification into
    matching against a closed list of real people rather than open-ended guessing.
    """
    system_prompt = load_prompt("speakers")
    user_content = (
        f"Here is the structured meeting summary:\n\n{_summary_as_text(context)}"
        f"\n\nHere is the transcript:\n\n{transcript}"
    )
    if roster:
        user_content = f"TEAM ROSTER: {roster_line(roster)}\n\n{user_content}"
    return ask(system_prompt, user_content, max_tokens=2500).strip()
