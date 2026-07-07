"""Thin wrapper around the Anthropic API.

Everything the three stages need to talk to Claude lives here: loading a prompt
file, sending a request, and safely pulling JSON out of the reply. Keeping this in
one place means the stages stay small and easy to read.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from anthropic import Anthropic

# Newest Claude model at time of writing.
MODEL = "claude-sonnet-5"

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"


class WorkbenchError(Exception):
    """A friendly, human-readable error we can show the user without a traceback."""


def _get_client() -> Anthropic:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise WorkbenchError(
            "No ANTHROPIC_API_KEY found.\n"
            "  1. Copy .env.example to .env\n"
            "  2. Put your key from console.anthropic.com in it\n"
            "  3. Run again."
        )
    return Anthropic(api_key=api_key)


def load_prompt(name: str) -> str:
    """Read a prompt file from the prompts/ folder (e.g. load_prompt('extract'))."""
    path = PROMPTS_DIR / f"{name}.md"
    if not path.exists():
        raise WorkbenchError(f"Prompt file not found: {path}")
    return path.read_text(encoding="utf-8")


def ask(system_prompt: str, user_content: str, max_tokens: int = 4000) -> str:
    """Send one request to Claude and return the plain text reply."""
    client = _get_client()
    try:
        message = client.messages.create(
            model=MODEL,
            max_tokens=max_tokens,
            system=system_prompt,
            messages=[{"role": "user", "content": user_content}],
        )
    except Exception as exc:  # network / API / auth problems
        raise WorkbenchError(f"Could not reach the Claude API: {exc}") from exc
    return "".join(block.text for block in message.content if block.type == "text")


def _extract_json(text: str) -> str:
    """Pull the JSON out of a reply, even if the model wrapped it in ```json fences."""
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fenced:
        return fenced.group(1).strip()
    # Otherwise grab from the first { or [ to the last } or ].
    start = min(
        (i for i in (text.find("{"), text.find("[")) if i != -1),
        default=-1,
    )
    end = max(text.rfind("}"), text.rfind("]"))
    if start != -1 and end != -1:
        return text[start : end + 1]
    return text.strip()


def ask_json(system_prompt: str, user_content: str, max_tokens: int = 4000):
    """Ask Claude for JSON and parse it. Retries once if the reply isn't valid JSON."""
    for attempt in (1, 2):
        reply = ask(system_prompt, user_content, max_tokens=max_tokens)
        try:
            return json.loads(_extract_json(reply))
        except json.JSONDecodeError:
            if attempt == 2:
                raise WorkbenchError(
                    "Claude did not return valid JSON after two tries. "
                    "This is usually temporary — please run again."
                )
            # Nudge the model to be stricter on the retry.
            user_content = (
                user_content
                + "\n\nIMPORTANT: Your previous reply was not valid JSON. "
                "Return ONLY the JSON, with no extra text or fences."
            )
