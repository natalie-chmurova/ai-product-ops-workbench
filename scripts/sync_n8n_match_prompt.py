#!/usr/bin/env python3
"""Write prompts/match.md into the n8n Match agent node, so the two cannot drift.

    python scripts/sync_n8n_match_prompt.py                       # the repo export
    python scripts/sync_n8n_match_prompt.py /tmp/sync-live.json    # an exported live copy

The node holds an n8n expression: the same text, with n8n placeholders where the
Python module has format fields. tests/test_n8n_parity.py fails when they differ.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT = ROOT / "n8n" / "meeting-to-clickup-sync.workflow.json"
NODE = "Match agent (Claude)"
PLACEHOLDERS = {
    "{board}": "{{ $('Board summary').first().json.boardText }}",
    "{name}": "{{ $json.name }}",
    "{detail}": "{{ $json.description }}",
}


def render(prompt: str) -> str:
    """prompts/match.md -> the text of the n8n node (an expression, hence the '=')."""
    out = prompt
    for field, expression in PLACEHOLDERS.items():
        out = out.replace(field, expression)
    return "=" + out.rstrip("\n")


def patch(path: Path) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    node = next(n for n in data["nodes"] if n["name"] == NODE)
    prompt = (ROOT / "prompts" / "match.md").read_text(encoding="utf-8")
    node["parameters"]["messages"]["values"][0]["content"] = render(prompt)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"patched '{NODE}' in {path}")


if __name__ == "__main__":
    patch(Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT)
