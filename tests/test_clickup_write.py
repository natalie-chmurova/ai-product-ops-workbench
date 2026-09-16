"""Writing to ClickUp: what reaches it, and what a refused or dropped write answers.

A write never raises — it answers `(ok, info)`, and on not-ok the info is the reason, so
a run that applies many effects can report the ones that failed and keep its summary.
The requests are routed through the one transport the module makes them with (the
`transport` fixture), so these tests read the payload ClickUp would have received.
"""

from __future__ import annotations

import requests

from src import clickup

API = clickup.API
MAIN = f"{API}/list/main/task"
BACKLOG = f"{API}/list/backlog-list/task"
COMMENT = f"{API}/task/86abc/comment"

CREATED = {"id": "86new", "url": "https://app.clickup.com/t/86new"}


# --- creating a task ---------------------------------------------------------

def test_a_created_task_carries_the_payload_clickup_expects(transport):
    transport.answers(MAIN, CREATED)
    task = {"name": "[Dev] New alerting", "description": "Goal:\nalert on CDN errors",
            "priority": 2, "tags": ["ops"]}
    ok, info = clickup._create_task("main", task, assignee_id="42")
    assert (ok, info) == (True, "[Dev] New alerting")
    assert transport.calls[0].method == "POST"
    assert transport.calls[0].body == {
        "name": "[Dev] New alerting", "description": "Goal:\nalert on CDN errors",
        "priority": 2, "assignees": [42], "tags": ["ops"]}


def test_a_null_description_is_sent_as_an_empty_one(transport):
    # str(None) is "None": a model's "description": null used to reach ClickUp as that word.
    transport.answers(MAIN, CREATED)
    ok, _ = clickup._create_task("main", {"name": "[Dev] Null description",
                                          "description": None})
    assert ok
    assert transport.calls[0].body["description"] == ""


def test_a_rejected_tag_is_retried_without_the_tags(transport):
    # A tag the space does not have gets the whole create rejected; the task matters more
    # than its labels, so it is offered again without them.
    transport.answers(MAIN, status=400, text="Tag not found")
    transport.answers(MAIN, CREATED)
    ok, info = clickup._create_task("main", {"name": "x", "tags": ["nope"]})
    assert (ok, info) == (True, "x")
    assert len(transport.calls) == 2
    assert "tags" in transport.calls[0].body and "tags" not in transport.calls[1].body


def test_a_network_error_on_the_tagless_retry_is_a_reason_not_a_raise(transport):
    transport.answers(MAIN, status=400, text="Tag not found")
    transport.drops(MAIN, requests.ConnectionError("Connection reset by peer"))
    ok, info = clickup._create_task("main", {"name": "x", "tags": ["nope"]})
    assert ok is False
    assert "Connection reset by peer" in info


def test_a_create_that_never_reached_clickup_is_not_retried(transport):
    # A request that got no answer may still have been made: ClickUp can have created the
    # task and lost the reply. Offering it again is how one effect becomes two tasks, so
    # the tag-less retry is for a create ClickUp answered and refused, not for silence.
    transport.drops(MAIN, requests.ConnectionError("Connection reset by peer"))
    ok, info = clickup._create_task("main", {"name": "x", "tags": ["nope"]})
    assert ok is False and "Connection reset by peer" in info
    assert len(transport.calls) == 1


def test_a_refused_create_is_a_reason_naming_the_status(transport):
    transport.answers(MAIN, status=500, text="boom")
    ok, info = clickup._create_task("main", {"name": "x"})
    assert ok is False
    assert "500" in info and "boom" in info


# --- push_one: the owner, the list, the marker tags --------------------------

def test_push_one_routes_a_backlog_bug_and_tags_it(transport):
    transport.answers(BACKLOG, CREATED)
    task = {"name": "x", "owner": "Dana", "type": "bug", "destination": "backlog",
            "tags": ["search"]}
    res = clickup.push_one(task, "main", [], {"dana": "42"}, "backlog-list")
    assert transport.calls[0].url == BACKLOG
    assert transport.calls[0].body["assignees"] == [42]
    assert transport.calls[0].body["tags"] == ["search", "bug", "backlog"]
    assert res == {"ok": True, "info": "x", "assigned": True, "backlog": True}


def test_push_one_without_a_backlog_list_keeps_the_main_list(transport):
    transport.answers(MAIN, CREATED)
    res = clickup.push_one({"name": "x", "destination": "backlog"}, "main", [], {}, None)
    assert transport.calls[0].url == MAIN
    assert res["backlog"] is True          # the intent is still reported
    assert res["assigned"] is False


def test_push_one_does_not_mutate_the_caller_task(transport):
    transport.answers(MAIN, CREATED)
    task = {"name": "x", "type": "bug", "tags": []}
    clickup.push_one(task, "main", [], {}, None)
    assert task["tags"] == []


def test_push_one_reports_failure(transport):
    transport.answers(MAIN, status=500, text="boom")
    res = clickup.push_one({"name": "x"}, "main", [], {}, None)
    assert res["ok"] is False and "500" in res["info"]
    assert res["assigned"] is False and res["backlog"] is False


# --- commenting on an existing task ------------------------------------------

def test_a_comment_carries_its_text_and_notifies_nobody(transport):
    transport.answers(COMMENT, {"id": "c1"})
    assert clickup.add_comment("86abc", "From the meeting:\nbody") == (True, "86abc")
    assert transport.calls[0].url == COMMENT
    assert transport.calls[0].body == {"comment_text": "From the meeting:\nbody",
                                       "notify_all": False}


def test_a_refused_comment_is_a_reason_not_a_raise(transport):
    transport.answers(COMMENT, status=401, text="Token invalid")
    ok, info = clickup.add_comment("86abc", "text")
    assert ok is False
    assert "401" in info and "86abc" in info


def test_a_dropped_comment_is_a_reason_not_a_raise(transport):
    transport.drops(COMMENT, requests.ConnectionError("Connection reset by peer"))
    ok, info = clickup.add_comment("86abc", "text")
    assert ok is False
    assert "Connection reset by peer" in info


def test_a_write_with_no_token_is_a_reason_not_a_raise(monkeypatch, transport):
    # Every other write failure comes back as a reason for the run's summary; a missing
    # token used to be the one that stopped the loop with an exception instead.
    monkeypatch.delenv("CLICKUP_API_TOKEN", raising=False)
    ok, info = clickup.add_comment("86abc", "text")
    assert ok is False
    assert "CLICKUP_API_TOKEN" in info
    assert transport.calls == []
