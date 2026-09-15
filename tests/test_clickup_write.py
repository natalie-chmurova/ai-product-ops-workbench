"""Writing one task: owner, backlog routing, marker tags — no network."""

from src import clickup


class Response:
    def __init__(self, status: int, text: str = ""):
        self.status_code = status
        self.text = text


def _capture(monkeypatch, ok=True):
    calls = []

    def fake_create(target, task, assignee_id):
        calls.append((target, task, assignee_id))
        return ok, task["name"] if ok else "500: boom"

    monkeypatch.setattr(clickup, "_create_task", fake_create)
    return calls


def test_push_one_routes_a_backlog_bug_and_tags_it(monkeypatch):
    calls = _capture(monkeypatch)
    task = {"name": "x", "owner": "Dana", "type": "bug", "destination": "backlog",
            "tags": ["search"]}
    res = clickup.push_one(task, "main", [], {"dana": "42"}, "backlog-list")
    target, sent, assignee = calls[0]
    assert target == "backlog-list" and assignee == "42"
    assert sent["tags"] == ["search", "bug", "backlog"]
    assert res == {"ok": True, "info": "x", "assigned": True, "backlog": True}


def test_push_one_without_a_backlog_list_keeps_the_main_list(monkeypatch):
    calls = _capture(monkeypatch)
    res = clickup.push_one({"name": "x", "destination": "backlog"}, "main", [], {}, None)
    assert calls[0][0] == "main"
    assert res["backlog"] is True          # the intent is still reported
    assert res["assigned"] is False


def test_push_one_does_not_mutate_the_caller_task(monkeypatch):
    _capture(monkeypatch)
    task = {"name": "x", "type": "bug", "tags": []}
    clickup.push_one(task, "main", [], {}, None)
    assert task["tags"] == []


def test_push_one_reports_failure(monkeypatch):
    _capture(monkeypatch, ok=False)
    res = clickup.push_one({"name": "x"}, "main", [], {}, None)
    assert res["ok"] is False and "500" in res["info"]
    assert res["assigned"] is False and res["backlog"] is False


def test_a_null_description_is_sent_as_an_empty_one(monkeypatch):
    # str(None) is "None": a model's "description": null used to reach ClickUp as that word.
    sent = []
    monkeypatch.setenv("CLICKUP_API_TOKEN", "pk_test")
    monkeypatch.setattr(clickup.requests, "post",
                        lambda url, **kwargs: sent.append(kwargs["json"]) or Response(200))
    ok, _ = clickup._create_task("list1", {"name": "[Dev] Null description", "description": None})
    assert ok
    assert sent[0]["description"] == ""
