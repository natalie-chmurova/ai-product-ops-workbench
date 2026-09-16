"""Reading ClickUp: what a good answer produces, and what every bad one says.

Every test here routes answers through the one transport the module makes its requests
with (the `transport` fixture), so what is exercised is the public functions themselves —
the board, the picker's lists, the workspace's members — against answers a real ClickUp
can give: success, a 401, a dropped connection, an HTML error page from a proxy, and a
200 whose JSON is not the shape the reader expects.
"""

from __future__ import annotations

import pytest

from src import clickup
from src.client import WorkbenchError

API = clickup.API
TEAM = "9018"

BOARD = f"{API}/list/123/task"
SPACES = f"{API}/team/{TEAM}/space"
SPACE_LISTS = f"{API}/space/s1/list"
FOLDERS = f"{API}/space/s1/folder"
FOLDER_LISTS = f"{API}/folder/f1/list"
TEAMS = f"{API}/team"

WORKSPACE = {
    SPACES: {"spaces": [{"id": "s1", "name": "Product"}]},
    SPACE_LISTS: {"lists": [{"id": "l1", "name": "Sprint"}]},
    FOLDERS: {"folders": [{"id": "f1", "name": "Roadmap"}]},
    FOLDER_LISTS: {"lists": [{"id": "l2", "name": "Q4"}]},
}


def _task(i: int) -> dict:
    return {"id": f"t{i}", "name": f"Task {i}", "status": {"status": "to do"},
            "assignees": [], "due_date": None}


def _workspace(transport, skip: str = "") -> None:
    """Route the four requests the picker makes, leaving out the one the test routed."""
    for url, body in WORKSPACE.items():
        if url != skip:
            transport.answers(url, body)


def _with_workspace(monkeypatch) -> None:
    monkeypatch.setenv("CLICKUP_TEAM_ID", TEAM)


# --- the board ---------------------------------------------------------------

def test_unconfigured_board_is_empty_not_an_error(monkeypatch, transport):
    monkeypatch.delenv("CLICKUP_LIST_ID", raising=False)
    assert clickup.get_tasks() == []
    assert transport.calls == []


def test_a_board_row_is_what_every_consumer_expects(transport):
    transport.answers(BOARD, {"tasks": [{
        "id": "a", "name": "n", "status": {"status": "in progress"},
        "assignees": [{"username": "Dana"}], "due_date": "1787097600000"}], "last_page": True})
    assert clickup.get_tasks("123") == [{"id": "a", "name": "n", "status": "in progress",
                                         "assignees": ["Dana"], "due_date": "2026-08-19"}]


def test_a_failing_read_raises_instead_of_pretending_the_board_is_empty(transport):
    # An expired token used to return [] — and every meeting point became new work.
    transport.answers(BOARD, status=401, text="Token invalid")
    with pytest.raises(WorkbenchError) as exc:
        clickup.get_tasks("123")
    assert "401" in str(exc.value)
    assert "CLICKUP_API_TOKEN" in str(exc.value)


def test_every_page_is_read(transport):
    transport.answers(BOARD, {"tasks": [_task(1), _task(2)], "last_page": False})
    transport.answers(BOARD, {"tasks": [_task(3)], "last_page": True})
    board = clickup.get_tasks("123")
    assert [t["id"] for t in board] == ["t1", "t2", "t3"]
    assert [call.params["page"] for call in transport.calls] == [0, 1]


def test_a_single_page_without_last_page_flag_still_stops(transport):
    transport.answers(BOARD, {"tasks": [_task(1)]})
    assert len(clickup.get_tasks("123")) == 1


def test_network_failure_is_a_workbench_error(transport):
    transport.drops(BOARD)
    with pytest.raises(WorkbenchError):
        clickup.get_tasks("123")


def test_a_board_answer_that_is_not_json_is_a_sentence(transport):
    transport.answers(BOARD, text="<html>502 Bad Gateway</html>")
    with pytest.raises(WorkbenchError) as exc:
        clickup.get_tasks("123")
    assert "JSON" in str(exc.value)


def test_a_board_answer_of_the_wrong_shape_is_a_sentence_not_a_traceback(transport):
    # A 200 whose tasks are not a list of tasks used to reach _task_row and raise
    # AttributeError from inside the read.
    transport.answers(BOARD, {"tasks": "none"})
    with pytest.raises(WorkbenchError) as exc:
        clickup.get_tasks("123")
    assert "tasks" in str(exc.value)


def test_a_repeating_page_response_does_not_loop_forever(transport):
    # A malformed "repeating page" response keeps last_page False with non-empty tasks on
    # every call. The ceiling must be enforced inside the loop, or this hangs forever
    # issuing HTTP calls. The test bounds its own exposure: the routed answer is the only
    # one, so a run that never stopped would keep counting calls — assert it stopped.
    transport.answers(BOARD, {"tasks": [_task(i) for i in range(50)], "last_page": False})
    with pytest.raises(WorkbenchError):
        clickup.get_tasks("123")
    assert len(transport.calls) < 10


def test_a_board_over_the_ceiling_raises_naming_the_count(transport):
    total = clickup.MAX_BOARD + 1
    transport.answers(BOARD, {"tasks": [_task(i) for i in range(total)], "last_page": True})
    with pytest.raises(WorkbenchError) as exc:
        clickup.get_tasks("123")
    assert str(total) in str(exc.value)
    assert str(clickup.MAX_BOARD) in str(exc.value)


# --- the list picker ---------------------------------------------------------

def test_no_workspace_means_no_lists_and_no_request(monkeypatch, transport):
    monkeypatch.delenv("CLICKUP_TEAM_ID", raising=False)
    assert clickup.get_lists() == []
    assert transport.calls == []


def test_a_workspace_lists_its_lists_with_their_space(monkeypatch, transport):
    _with_workspace(monkeypatch)
    _workspace(transport)
    assert clickup.get_lists() == [
        {"id": "l1", "name": "Sprint", "space": "Product"},
        {"id": "l2", "name": "Roadmap / Q4", "space": "Product"},
    ]


@pytest.mark.parametrize("url", list(WORKSPACE), ids=lambda url: url.replace(API, ""))
def test_a_failing_list_read_raises_naming_the_status(monkeypatch, transport, url):
    # An expired token made the picker read as "No ClickUp list configured", and the run
    # went ahead board-blind. Whichever of its requests fails, get_lists has to say so.
    _with_workspace(monkeypatch)
    transport.answers(url, status=401, text="Token invalid")
    _workspace(transport, skip=url)
    with pytest.raises(WorkbenchError) as exc:
        clickup.get_lists()
    assert "401" in str(exc.value)
    assert "CLICKUP_API_TOKEN" in str(exc.value)


def test_a_network_error_listing_lists_is_a_workbench_error(monkeypatch, transport):
    _with_workspace(monkeypatch)
    transport.drops(SPACES)
    with pytest.raises(WorkbenchError):
        clickup.get_lists()


def test_a_list_read_that_is_not_json_is_a_workbench_error(monkeypatch, transport):
    _with_workspace(monkeypatch)
    transport.answers(FOLDER_LISTS, text="<html>502 Bad Gateway</html>")
    _workspace(transport, skip=FOLDER_LISTS)
    with pytest.raises(WorkbenchError) as exc:
        clickup.get_lists()
    assert "JSON" in str(exc.value)


def test_an_answer_that_is_not_an_object_is_a_sentence_not_a_traceback(monkeypatch, transport):
    # A 200 carrying a JSON list — one proxy's way of saying "no content" — used to reach
    # .get() on a list and stop the page with an AttributeError.
    _with_workspace(monkeypatch)
    transport.answers(SPACES, [])
    with pytest.raises(WorkbenchError) as exc:
        clickup.get_lists()
    assert "object" in str(exc.value)


def test_a_space_with_no_id_or_name_is_a_sentence_not_a_traceback(monkeypatch, transport):
    # Anything but {id, name} used to leave the picker with a KeyError traceback.
    _with_workspace(monkeypatch)
    transport.answers(SPACES, {"spaces": [{"private": True}]})
    with pytest.raises(WorkbenchError) as exc:
        clickup.get_lists()
    assert "id" in str(exc.value) and "name" in str(exc.value)


# --- the workspace's members -------------------------------------------------

def test_no_workspace_means_no_members_and_no_request(monkeypatch, transport):
    monkeypatch.delenv("CLICKUP_TEAM_ID", raising=False)
    assert clickup.get_members() == []
    assert transport.calls == []


def test_the_members_of_this_workspace_come_back_as_id_and_name(monkeypatch, transport):
    _with_workspace(monkeypatch)
    transport.answers(TEAMS, {"teams": [
        {"id": "other", "members": [{"user": {"id": 1, "username": "Somebody else"}}]},
        {"id": TEAM, "members": [
            {"user": {"id": 222150225, "username": "Natallia Chmurova"}},
            {"user": {"id": 999, "username": "Marco Rossi"}},
            {"user": {}},                       # an invitation nobody accepted
        ]},
    ]})
    assert clickup.get_members() == [{"id": "222150225", "name": "Natallia Chmurova"},
                                     {"id": "999", "name": "Marco Rossi"}]


def test_a_failing_member_read_is_a_workbench_error(monkeypatch, transport):
    _with_workspace(monkeypatch)
    transport.answers(TEAMS, status=401, text="Token invalid")
    with pytest.raises(WorkbenchError) as exc:
        clickup.get_members()
    assert "401" in str(exc.value)


def test_a_dropped_member_read_is_a_workbench_error(monkeypatch, transport):
    _with_workspace(monkeypatch)
    transport.drops(TEAMS)
    with pytest.raises(WorkbenchError):
        clickup.get_members()


# --- what every request carries ----------------------------------------------

def test_every_request_carries_the_token_and_a_timeout(transport):
    transport.answers(BOARD, {"tasks": [], "last_page": True})
    transport.answers(f"{API}/task/86abc/comment", {"id": "c1"})
    clickup.get_tasks("123")
    clickup.add_comment("86abc", "text")
    assert len(transport.calls) == 2
    for call in transport.calls:
        assert call.headers["Authorization"] == "pk_test"
        assert call.headers["Content-Type"] == "application/json"
        assert call.timeout


def test_a_read_with_no_token_says_so_before_asking(monkeypatch, transport):
    monkeypatch.delenv("CLICKUP_API_TOKEN", raising=False)
    with pytest.raises(WorkbenchError) as exc:
        clickup.get_tasks("123")
    assert "CLICKUP_API_TOKEN" in str(exc.value)
    assert transport.calls == []
