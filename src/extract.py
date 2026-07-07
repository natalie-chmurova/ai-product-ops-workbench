"""Stage 1 — the "Understander".

Reads the raw transcript and turns the messy discussion into one clean, structured
summary (a Python dict). Every later stage builds on this single shared summary, so
all the documents stay consistent with each other.
"""

from __future__ import annotations

from .client import ask_json, load_prompt


def extract_context(transcript: str) -> dict:
    """Transcript text -> structured meeting summary."""
    if not transcript or len(transcript.strip()) < 40:
        raise ValueError(
            "The transcript looks empty or too short to analyze. "
            "Please provide a real meeting transcript."
        )
    system_prompt = load_prompt("extract")
    user_content = f"Here is the meeting transcript:\n\n{transcript}"
    return ask_json(system_prompt, user_content, max_tokens=6000)
