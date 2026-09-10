"""Reading the board: unconfigured is empty, failing is an error, paged is complete."""

from __future__ import annotations

import pytest

from src import clickup
from src.client import WorkbenchError


class FakeResponse:
    def __init__(self, status: int, payload: dict | None = None, text: str = ""):
        self.status_code = status
        self._payload = payload or {}
        self.text = text

    def json(self) -> dict:
        return self._payload


def _task(i: int) -> dict:
    return {"id": f"t{i}", "name": f"Task {i}", "status": {"status": "to do"},
            "assignees": [], "due_date": None}


def test_unconfigured_board_is_empty_not_an_error(monkeypatch):
    monkeypatch.delenv("CLICKUP_LIST_ID", raising=False)
    assert clickup.get_tasks() == []


def test_a_failing_read_raises_instead_of_pretending_the_board_is_empty(monkeypatch):
    # An expired token used to return [] — and every meeting point became new work.
    monkeypatch.setenv("CLICKUP_API_TOKEN", "pk_test")
    monkeypatch.setattr(clickup.requests, "get",
                        lambda *a, **k: FakeResponse(401, text="Token invalid"))
    with pytest.raises(WorkbenchError) as exc:
        clickup.get_tasks("123")
    assert "401" in str(exc.value)
    assert "CLICKUP_API_TOKEN" in str(exc.value)


def test_every_page_is_read(monkeypatch):
    monkeypatch.setenv("CLICKUP_API_TOKEN", "pk_test")
    pages = {
        0: {"tasks": [_task(1), _task(2)], "last_page": False},
        1: {"tasks": [_task(3)], "last_page": True},
    }
    seen = []

    def fake_get(url, params=None, **kwargs):
        seen.append(params["page"])
        return FakeResponse(200, pages[params["page"]])

    monkeypatch.setattr(clickup.requests, "get", fake_get)
    board = clickup.get_tasks("123")
    assert [t["id"] for t in board] == ["t1", "t2", "t3"]
    assert seen == [0, 1]


def test_a_single_page_without_last_page_flag_still_stops(monkeypatch):
    monkeypatch.setenv("CLICKUP_API_TOKEN", "pk_test")
    monkeypatch.setattr(clickup.requests, "get",
                        lambda *a, **k: FakeResponse(200, {"tasks": [_task(1)]}))
    assert len(clickup.get_tasks("123")) == 1


def test_network_failure_is_a_workbench_error(monkeypatch):
    monkeypatch.setenv("CLICKUP_API_TOKEN", "pk_test")

    def boom(*a, **k):
        raise clickup.requests.ConnectionError("down")

    monkeypatch.setattr(clickup.requests, "get", boom)
    with pytest.raises(WorkbenchError):
        clickup.get_tasks("123")


def test_task_row_keeps_the_board_shape():
    row = clickup._task_row({"id": "a", "name": "n", "status": {"status": "in progress"},
                             "assignees": [{"username": "Dana"}], "due_date": "1787097600000"})
    assert row == {"id": "a", "name": "n", "status": "in progress",
                   "assignees": ["Dana"], "due_date": "2026-08-19"}


def test_a_repeating_page_response_does_not_loop_forever(monkeypatch):
    # A malformed "repeating page" response keeps last_page False with non-empty
    # tasks on every call. The ceiling must be enforced inside the loop, or this
    # hangs forever issuing HTTP calls. Bound our own exposure: fail the test with
    # an AssertionError (not a hang) if get_tasks calls requests.get more than 50
    # times without stopping.
    monkeypatch.setenv("CLICKUP_API_TOKEN", "pk_test")
    page = {"tasks": [_task(i) for i in range(50)], "last_page": False}
    calls = {"n": 0}

    def fake_get(url, params=None, **kwargs):
        calls["n"] += 1
        if calls["n"] > 50:
            raise AssertionError(
                "get_tasks did not stop paging a repeating response within 50 calls"
            )
        return FakeResponse(200, page)

    monkeypatch.setattr(clickup.requests, "get", fake_get)
    with pytest.raises(WorkbenchError):
        clickup.get_tasks("123")


def test_a_board_over_the_ceiling_raises_naming_the_count(monkeypatch):
    monkeypatch.setenv("CLICKUP_API_TOKEN", "pk_test")
    total = clickup.MAX_BOARD + 1

    def fake_get(url, params=None, **kwargs):
        return FakeResponse(200, {"tasks": [_task(i) for i in range(total)], "last_page": True})

    monkeypatch.setattr(clickup.requests, "get", fake_get)
    with pytest.raises(WorkbenchError) as exc:
        clickup.get_tasks("123")
    assert str(total) in str(exc.value)
    assert str(clickup.MAX_BOARD) in str(exc.value)
