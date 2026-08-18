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
