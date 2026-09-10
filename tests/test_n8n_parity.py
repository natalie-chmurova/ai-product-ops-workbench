"""The n8n export must carry what the Python path carries. Drift here is silent."""

import json
from pathlib import Path

from scripts.sync_n8n_match_prompt import NODE, render

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / "n8n" / "meeting-to-clickup-sync.workflow.json"


def _node(name: str) -> dict:
    data = json.loads(WORKFLOW.read_text(encoding="utf-8"))
    return next(n for n in data["nodes"] if n["name"] == name)


def test_render_swaps_format_fields_for_n8n_expressions():
    out = render("EXISTING TASKS:\n{board}\nName: {name}\nDetail: {detail}\n")
    assert out.startswith("=EXISTING TASKS:")
    assert "{{ $('Board summary').first().json.boardText }}" in out
    assert "{{ $json.name }}" in out and "{{ $json.description }}" in out
    assert "{board}" not in out and not out.endswith("\n")


def test_the_match_agent_carries_the_shared_prompt():
    # This is the drift WB-21 closed for the eval, found again in n8n on 2026-09-09.
    expected = render((ROOT / "prompts" / "match.md").read_text(encoding="utf-8"))
    assert _node(NODE)["parameters"]["messages"]["values"][0]["content"] == expected


def test_the_board_summary_shows_status_owner_and_due():
    code = _node("Board summary")["parameters"]["jsCode"]
    for marker in ("status:", "owner:", "due:"):
        assert marker in code


def test_state_and_log_both_live_under_wb_home():
    for name in ("Idempotency check", "Mark processed", "Log decision"):
        code = _node(name)["parameters"]["jsCode"]
        assert "$env.WB_HOME" in code, name
        assert "'state/processed_effects.jsonl'" not in code, name


def test_mark_processed_commits_one_effect_not_the_whole_batch():
    # It ran once for all items and committed every fresh key on the first successful
    # apply — so an item a human then rejected, or one still waiting in Telegram, was
    # recorded as applied. The app shares this store, so those effects vanished there too.
    node = _node("Mark processed")
    assert node["parameters"]["mode"] == "runOnceForEachItem"
    code = node["parameters"]["jsCode"]
    assert "$('Idempotency check').item" in code
    assert ".all()" not in code
