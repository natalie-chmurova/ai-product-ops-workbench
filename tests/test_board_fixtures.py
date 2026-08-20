"""Board fixtures: a board read from a file instead of the live tracker."""

import json

import pytest

from src.clickup import load_board_fixture
from src.client import WorkbenchError

FIXTURE = {
    "transcript": "samples/transcript_messy_1.txt",
    "status": "DRAFT — awaiting Natallia's validation",
    "tasks": [
        {
            "id": "B1",
            "name": "[Release] Cut the August release",
            "status": "in progress",
            "assignees": ["Dana"],
            "due_date": "2026-08-19",
        }
    ],
}


def test_fixture_loads_in_the_shape_get_tasks_returns(tmp_path):
    path = tmp_path / "board.json"
    path.write_text(json.dumps(FIXTURE), encoding="utf-8")
    board = load_board_fixture(path)
    assert board == FIXTURE["tasks"]


def test_fixture_fills_in_missing_optional_fields(tmp_path):
    path = tmp_path / "board.json"
    path.write_text(
        json.dumps({"tasks": [{"id": "B1", "name": "Only the basics"}]}), encoding="utf-8"
    )
    board = load_board_fixture(path)
    assert board == [
        {"id": "B1", "name": "Only the basics", "status": "", "assignees": [], "due_date": ""}
    ]


def test_each_task_gets_its_own_assignees_list(tmp_path):
    """A shared default list would let one task's owners leak into another's."""
    path = tmp_path / "board.json"
    path.write_text(
        json.dumps({"tasks": [{"id": "B1", "name": "One"}, {"id": "B2", "name": "Two"}]}),
        encoding="utf-8",
    )
    board = load_board_fixture(path)
    board[0]["assignees"].append("Dana")
    assert board[1]["assignees"] == []


def test_missing_fixture_names_the_path(tmp_path):
    with pytest.raises(WorkbenchError) as exc:
        load_board_fixture(tmp_path / "nope.json")
    assert "nope.json" in str(exc.value)


def test_malformed_fixture_fails_loudly(tmp_path):
    path = tmp_path / "board.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(WorkbenchError):
        load_board_fixture(path)


# --- the due date, as ClickUp actually sends it -------------------------------
# ClickUp returns due_date as epoch MILLISECONDS in a JSON string, or null. The
# live demo board has no dated tasks, so a run against it cannot exercise this;
# these vectors are the proof instead.

from src.clickup import _iso_date


def test_due_date_from_clickups_millisecond_string():
    # 2026-08-19T00:00:00Z
    assert _iso_date("1787097600000") == "2026-08-19"


def test_due_date_from_an_integer():
    assert _iso_date(1787097600000) == "2026-08-19"


def test_due_date_absent_is_empty_not_epoch_zero():
    assert _iso_date(None) == ""
    assert _iso_date("") == ""
    assert _iso_date(0) == ""


def test_due_date_that_makes_no_sense_does_not_crash_the_run():
    assert _iso_date("tomorrow") == ""


# --- what the agent is shown --------------------------------------------------

from src.reconcile import board_summary

RICH_BOARD = [
    {
        "id": "B1",
        "name": "[Release] Cut the August release",
        "status": "in progress",
        "assignees": ["Dana"],
        "due_date": "2026-08-19",
    },
    {"id": "B2", "name": "Bare task", "status": "", "assignees": [], "due_date": ""},
    {
        "id": "B3",
        "name": "Shared task",
        "status": "to do",
        "assignees": ["Sam", "Marco"],
        "due_date": "",
    },
]


def test_summary_shows_status_owner_and_due():
    line = board_summary(RICH_BOARD).splitlines()[0]
    assert line == (
        "B1 | [Release] Cut the August release | status: in progress "
        "| owner: Dana | due: 2026-08-19"
    )


def test_summary_omits_empty_fields_entirely():
    assert board_summary(RICH_BOARD).splitlines()[1] == "B2 | Bare task"


def test_summary_joins_several_assignees():
    assert board_summary(RICH_BOARD).splitlines()[2] == "B3 | Shared task | status: to do | owner: Sam, Marco"


# --- why an escalation happened -----------------------------------------------

from src.reconcile import parse_decision, split_by_confidence

SMALL_BOARD = [{"id": "86abc", "name": "[Payments] Fix saved cards"}]


def test_unreadable_reply_is_named_as_such():
    d = parse_decision("the model rambled instead of answering", SMALL_BOARD)
    assert d["escalation_cause"] == "unreadable"
    assert d["confidence"] == 0.0


def test_update_naming_a_task_not_on_the_board():
    reply = "DECISION: UPDATE\nTASK_ID: 99zzz\nCONFIDENCE: 0.9\nREASON: same work"
    d = parse_decision(reply, SMALL_BOARD)
    assert d["escalation_cause"] == "phantom_target"
    assert d["confidence"] == 0.0


def test_an_honest_answer_has_no_failure_cause():
    reply = "DECISION: UPDATE\nTASK_ID: 86abc\nCONFIDENCE: 0.9\nREASON: same work"
    assert parse_decision(reply, SMALL_BOARD)["escalation_cause"] == ""


def test_the_gate_labels_honest_doubt():
    doubtful = {"name": "x", "decision": "NEW", "target_id": "", "confidence": 0.5, "escalation_cause": ""}
    broken = {"name": "y", "decision": "UPDATE", "target_id": "", "confidence": 0.0, "escalation_cause": "unreadable"}
    _, _, ask = split_by_confidence([doubtful, broken])
    assert [d["escalation_cause"] for d in ask] == ["low_confidence", "unreadable"]


def test_the_gate_does_not_relabel_a_confident_decision():
    confident = {"name": "z", "decision": "NEW", "target_id": "", "confidence": 0.95, "escalation_cause": ""}
    create, _, ask = split_by_confidence([confident])
    assert not ask
    assert create[0]["escalation_cause"] == ""


# --- scoring the effect -------------------------------------------------------

from evals.eval_effects import score


def test_a_correct_comment_needs_the_right_target():
    entries = [
        {"id": "gt1", "expected_effect": "comment", "expected_target": "B1"},
        {"id": "gt2", "expected_effect": "comment", "expected_target": "B1"},
    ]
    decided = [
        {"id": "gt1", "effect": "comment", "target_id": "B1", "escalation_cause": ""},
        {"id": "gt2", "effect": "comment", "target_id": "B9", "escalation_cause": ""},
    ]
    result = score(entries, decided)
    assert result["effect_correct"] == 2   # both chose to comment
    assert result["target_correct"] == 1   # only one aimed correctly


def test_a_guardrail_escalation_is_not_a_correct_ask():
    entries = [{"id": "gt1", "expected_effect": "ask"}, {"id": "gt2", "expected_effect": "ask"}]
    decided = [
        {"id": "gt1", "effect": "ask", "target_id": "", "escalation_cause": "low_confidence"},
        {"id": "gt2", "effect": "ask", "target_id": "", "escalation_cause": "unreadable"},
    ]
    result = score(entries, decided)
    assert result["effect_correct"] == 1
    assert result["by_cause"]["unreadable"] == 1


def test_unimplemented_effects_score_zero():
    entries = [{"id": "n1", "expected_effect": "verify_deadline", "expected_target": "B2"}]
    decided = [{"id": "n1", "effect": "create", "target_id": "", "escalation_cause": ""}]
    result = score(entries, decided)
    assert result["effect_correct"] == 0
    assert result["per_effect"]["verify_deadline"] == {"total": 1, "correct": 0}


def test_a_miss_records_what_the_agent_was_about_to_do():
    entries = [{"id": "gt1", "expected_effect": "comment", "expected_target": "B1"}]
    decided = [
        {
            "id": "gt1",
            "effect": "create",
            "target_id": "",
            "escalation_cause": "",
            "decision": "NEW",
            "reason": "nothing on the board covers this",
        }
    ]
    miss = score(entries, decided)["misses"][0]
    assert miss["expected"] == "comment" and miss["got"] == "create"
    assert miss["intent"] == "NEW NONE"
