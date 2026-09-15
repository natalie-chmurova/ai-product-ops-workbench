"""The n8n export must carry what the Python path carries. Drift here is silent."""

import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts.sync_n8n_match_prompt import NODE, find_node, patch, render
from src.idempotency import comment_key, create_key
from src.clickup import _task_row
from src.reconcile import board_summary, parse_decision, reconcile

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / "n8n" / "meeting-to-clickup-sync.workflow.json"

# Fakes just enough of the n8n Code-node runtime for a node's own jsCode to run under
# plain Node, unmodified, inside `new Function`. It reads a job from stdin:
#   code, items  the node's jsCode and its input items (each item's json)
#   mode         "runOnceForEachItem" runs the code once per item, with $json and
#                $input.item set, as n8n does; anything else runs it once over all items
#   env          what $env holds (empty unless given)
#   nodes        other nodes' output items by name: $('Name').first() is the first one,
#                and $('Name').item the one paired with the current item (same index)
# `require` hands out fs and crypto only, the modules the n8n launcher allows.
_NODE_RUNNER = r"""
const fs = require('fs');
const job = JSON.parse(fs.readFileSync(0, 'utf8'));
const items = job.items.map(json => ({ json }));
const perItem = job.mode === 'runOnceForEachItem';
const allowed = new Set(['fs', 'crypto']);
const nodeRequire = name => {
  if (!allowed.has(name)) throw new Error(`require('${name}') is not allowed in the Code node`);
  return require(name);
};
const others = job.nodes || {};
const lookup = index => name => {
  if (!(name in others)) throw new Error(`the stand-in has no output for node '${name}'`);
  return { first: () => ({ json: others[name][0] }), item: { json: others[name][index] } };
};
const run = index => new Function('$input', 'items', '$json', '$', '$env', 'require', job.code)(
  { all: () => items, item: perItem ? items[index] : undefined },
  items,
  perItem ? items[index].json : undefined,
  lookup(index),
  job.env || {},
  nodeRequire
);
const result = perItem ? items.map((_, i) => run(i)) : run(0);
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


def _needs_node() -> None:
    if shutil.which("node") is None:
        pytest.skip("node is not installed; running an n8n node's own code needs it")


def _run_node(name: str, items: list, **stand_in) -> list:
    """Run one node's own jsCode from the export under node; return its output items' json.

    `stand_in` is what the node reads besides its input: `env` for $env, `nodes` for
    $('Name'). The mode is the node's own, so a per-item node runs once per item.
    """
    params = _node(name)["parameters"]
    job = {"code": params["jsCode"], "mode": params.get("mode", "runOnceForAllItems"),
           "items": items, **stand_in}
    proc = subprocess.run(["node", "-e", _NODE_RUNNER], input=json.dumps(job),
                          capture_output=True, text=True)
    if proc.returncode != 0:
        pytest.fail(f"the {name!r} node threw under node:\n{proc.stderr}")
    return [out["json"] for out in json.loads(proc.stdout)]


# --- one key spec: the app and the n8n Idempotency check key a point alike ---

KEY_BOARD = [{"id": "86abc", "name": "[Payments] Fix saved cards", "status": "",
              "assignees": [], "due_date": ""}]
# One meeting point each, with the match agent's verdict on it.
KEY_CASES = {
    "new-with-description": (
        {"name": "[Dev] New alerting", "description": "Goal:\nalert on CDN errors"}, "NEW"),
    "new-description-null": ({"name": "[Dev] Null description", "description": None}, "NEW"),
    "new-no-description-key": ({"name": "[Dev] No description"}, "NEW"),
    "update-body-from-description": (
        {"name": "[Payments] Saved cards", "description": "provider fixed the sandbox"}, "UPDATE"),
    "update-body-falls-back-to-name": (
        {"name": "[Dev] Crash fix in review", "description": None}, "UPDATE"),
}


def _task_id(decision: str) -> str:
    return KEY_BOARD[0]["id"] if decision == "UPDATE" else "NONE"


def _as_parse_decision_emits(point: dict, decision: str) -> dict:
    """What Idempotency check receives for this point: the point plus Parse decision's
    verdict. `target_id` is the TASK_ID as that node parses it, and `comment` is its own
    expression, (item.description || item.name || '').trim()."""
    return {**point, "is_update": decision == "UPDATE", "target_id": _task_id(decision),
            "comment": (point.get("description") or point.get("name") or "").strip()}


@pytest.fixture(scope="module")
def node_keys(tmp_path_factory):
    """Every case keyed by the Idempotency check node's own code, in one run. WB_HOME is
    an empty directory, so the node's read of the store finds nothing."""
    _needs_node()
    items = [_as_parse_decision_emits(point, decision) for point, decision in KEY_CASES.values()]
    out = _run_node("Idempotency check", items,
                    env={"WB_HOME": str(tmp_path_factory.mktemp("wb_home"))})
    return {case: item["idem_key"] for case, item in zip(KEY_CASES, out)}


@pytest.mark.parametrize("case", list(KEY_CASES))
def test_the_app_keys_a_point_as_the_idempotency_check_node_does(case, node_keys, monkeypatch):
    # The app and n8n share one store only if both compute one key per effect. The key
    # formula is pinned by tests/idempotency_vectors.json; what can drift is the assembly
    # -- which field, which fallback, which separator -- so this runs the node's own code
    # and compares its key with the app's for the same point, as reconcile() hands it on.
    point, decision = KEY_CASES[case]
    reply = f"DECISION: {decision}\nTASK_ID: {_task_id(decision)}\nCONFIDENCE: 0.9\nREASON: canned"
    monkeypatch.setattr("src.reconcile.ask", lambda system, prompt, max_tokens=400: reply)
    reconciled = reconcile([dict(point)], KEY_BOARD)[0]
    app_key = create_key(reconciled) if decision == "NEW" else comment_key(reconciled)
    assert app_key == node_keys[case]


# --- an UPDATE target counts only if it is exactly a board id ---

# Raw ClickUp tasks, as Fetch board hands them to Board summary: status, owner, due date.
SUMMARY_TASKS = [
    {"id": "86eyay0p7", "name": "[Checkout][Dev] Resolve payment sandbox tokenization",
     "status": {"status": "in progress"}, "assignees": [{"username": "natalie"}],
     "due_date": str(_epoch_ms(2026, 9, 18))},
    {"id": "86ey9z6rc", "name": "[ProductDetail][Dev] Fix crash on product detail",
     "status": {"status": "to do"}, "assignees": [], "due_date": None},
]
# What the agent might name as TASK_ID. All but the first and the last are words the
# board text carries without being an id.
TASK_IDS = {
    "real-id": "86eyay0p7",
    "truncated-id": "86eyay0p",
    "status-word": "progress",
    "owner-name": "natalie",
    "year": "2026",
    "none": "NONE",
}


def _update_reply(task_id: str) -> str:
    return f"DECISION: UPDATE\nTASK_ID: {task_id}\nCONFIDENCE: 0.95\nREASON: canned"


@pytest.fixture(scope="module")
def parse_decision_run():
    """Board summary's own code renders the board; Parse decision's own code reads every
    reply against it. Returns (Board summary's json, {case: Parse decision's json})."""
    _needs_node()
    summary = _run_node("Board summary", SUMMARY_TASKS)[0]
    point = {"name": "[Payments] Saved cards", "description": "provider fixed the sandbox"}
    replies = [{"content": [{"type": "text", "text": _update_reply(task_id)}]}
               for task_id in TASK_IDS.values()]
    parsed = _run_node("Parse decision", replies,
                       nodes={"Parse tasks": [point] * len(replies), "Board summary": [summary]})
    return summary, dict(zip(TASK_IDS, parsed))


def test_board_summary_hands_on_the_board_ids(parse_decision_run):
    summary, _ = parse_decision_run
    assert summary["ids"] == [t["id"] for t in SUMMARY_TASKS]


@pytest.mark.parametrize("case", list(TASK_IDS))
def test_parse_decision_takes_an_update_target_only_if_it_is_a_board_id(case, parse_decision_run):
    # The board text carries status, owner and due words, so a substring test against it
    # let "progress", a name, a year or a truncated id through at full confidence, down
    # the automatic branch. parse_decision() checks exact ids and blanks the target; the
    # node has to reach the same target and confidence on the same reply and board.
    _, parsed = parse_decision_run
    expected = parse_decision(_update_reply(TASK_IDS[case]), [_task_row(t) for t in SUMMARY_TASKS])
    assert (parsed[case]["target_id"], parsed[case]["confidence"]) == (
        expected["target_id"], expected["confidence"])
