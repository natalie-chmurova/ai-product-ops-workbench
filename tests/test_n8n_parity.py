"""The n8n export must carry what the Python path carries. Drift here is silent."""

import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts.sync_n8n_match_prompt import NODE, find_node, patch, render
from src.clickup import _task_row
from src.reconcile import board_summary

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / "n8n" / "meeting-to-clickup-sync.workflow.json"

# Fakes just enough of the n8n Code-node runtime for "Board summary" to run under
# plain Node: read {code, items} from stdin, expose items through $input.all(), and
# evaluate the node's own jsCode unmodified inside `new Function`.
_NODE_RUNNER = r"""
const fs = require('fs');
const payload = JSON.parse(fs.readFileSync(0, 'utf8'));
const items = payload.items.map(json => ({ json }));
const $input = { all: () => items };
const result = new Function('$input', payload.code)($input);
process.stdout.write(JSON.stringify(result));
"""


def _epoch_ms(year: int, month: int, day: int) -> int:
    """Midnight UTC on the given date, in epoch milliseconds -- unambiguous either
    side of a timezone, and the shape ClickUp's due_date carries."""
    return int(datetime(year, month, day, tzinfo=timezone.utc).timestamp() * 1000)


def _node(name: str) -> dict:
    data = json.loads(WORKFLOW.read_text(encoding="utf-8"))
    return find_node(data, name, WORKFLOW)


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


def test_board_summary_node_matches_python_board_summary_line_for_line():
    # The spec says the node renders the board "exactly as board_summary() does".
    # A substring check for "status:"/"owner:"/"due:" would pass even if the field
    # order, separator, or empty-field-omission logic drifted from src/reconcile.py.
    # This runs the node's own jsCode under Node against raw ClickUp-shaped tasks
    # and compares its output, line for line, with what Python produces for the
    # same tasks -- so a future regression to either side is caught, not eyeballed.
    if shutil.which("node") is None:
        pytest.skip("node is not installed; the Board summary parity check needs it")

    fixture = [
        {  # status, two assignees, due date as an epoch-ms *string*
            "id": "1",
            "name": "Ship the release notes",
            "status": {"status": "in progress"},
            "assignees": [{"username": "alice"}, {"username": "bob"}],
            "due_date": str(_epoch_ms(2024, 3, 5)),
        },
        {  # no assignees, due date explicitly null
            "id": "2",
            "name": "Review the onboarding doc",
            "status": {"status": "open"},
            "assignees": [],
            "due_date": None,
        },
        {  # status and assignees missing entirely, not just empty
            "id": "3",
            "name": "Untriaged task",
        },
        {  # due date as a number, not a string
            "id": "4",
            "name": "File the expense report",
            "status": {"status": "done"},
            "assignees": [{"username": "carol"}],
            "due_date": _epoch_ms(2024, 7, 19),
        },
    ]

    code = _node("Board summary")["parameters"]["jsCode"]
    proc = subprocess.run(
        ["node", "-e", _NODE_RUNNER],
        input=json.dumps({"code": code, "items": fixture}),
        capture_output=True,
        text=True,
        check=True,
    )
    node_json = json.loads(proc.stdout)[0]["json"]

    expected = board_summary([_task_row(t) for t in fixture])
    assert node_json["boardText"].split("\n") == expected.split("\n")
    assert node_json["count"] == len(fixture)


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


def test_patch_names_the_missing_node(tmp_path):
    # find_node() must fail loudly -- naming the sought node and the file it was
    # sought in -- instead of a bare StopIteration with no clue which was wrong.
    bogus = tmp_path / "no-match-agent.json"
    bogus.write_text(
        json.dumps({"nodes": [{"name": "Something else", "parameters": {}}]}),
        encoding="utf-8",
    )
    with pytest.raises(LookupError) as exc_info:
        patch(bogus)
    message = str(exc_info.value)
    assert NODE in message
    assert str(bogus) in message
