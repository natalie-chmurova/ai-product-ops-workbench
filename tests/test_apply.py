"""Applying a plan: every effect once, to the plan's own list, keys only after success.

`apply_plan` takes the plan and the asks a person ticked. The plan carries the list it
was reconciled against, and that is the only list it is written to — there is no
environment fallback, because a plan applied to a board it never saw is how duplicates
are made.
"""

import pytest

from src import apply
from src.client import WorkbenchError
from src.idempotency import IdempotencyStore, comment_key, create_key
from src.plan import build_plan

BOARD = [{"id": "86abc", "name": "[Payments] Fix saved cards"},
         {"id": "86def", "name": "[Android] Crash on product detail"}]

CREATE = {"name": "[Dev] New alerting", "description": "Goal:\nalert on CDN errors",
          "decision": "NEW", "target_id": "", "confidence": 0.9, "reason": "nothing covers it"}
COMMENT = {"name": "Saved cards update", "detail": "provider fixed the sandbox",
           "target_id": "86abc", "decision": "UPDATE", "confidence": 0.9,
           "reason": "same saved-cards work"}


def _plan(points=(CREATE, COMMENT), scope="list1", meeting_decisions=()):
    return build_plan(list(points), list(meeting_decisions), BOARD, scope)


def _wire(monkeypatch, create_ok=True, comment_ok=True):
    """The tracker faked at the ClickUp module's edge; returns what reached it."""
    created, commented = [], []
    monkeypatch.setattr(apply, "push_context", lambda: ([], {}, None))
    monkeypatch.setattr(
        apply, "push_one",
        lambda task, list_id, members, aliases, backlog_id: (
            created.append((task, list_id, backlog_id)) or
            {"ok": create_ok, "info": task["name"], "assigned": False, "backlog": False}
        ),
    )
    monkeypatch.setattr(
        apply, "add_comment",
        lambda task_id, text: (commented.append((task_id, text)) or (comment_ok, task_id)),
    )
    return created, commented


def test_a_plan_is_applied_and_counted(monkeypatch, tmp_path):
    created, commented = _wire(monkeypatch)
    store = IdempotencyStore(tmp_path / "s.jsonl")
    summary = apply.apply_plan(_plan(), store=store, meeting_title="Weekly sync",
                               when="2026-09-09")
    assert [c[0]["name"] for c in created] == ["[Dev] New alerting"]
    assert commented[0][0] == "86abc"
    assert summary["created"] == 1 and summary["commented"] == 1
    assert summary["already_applied"] == 0 and summary["repeated"] == 0
    assert summary["total"] == 2


def test_every_effect_goes_to_the_list_the_plan_was_built_against(monkeypatch, tmp_path):
    # One scope per run. A list configured in .env is not this plan's list, and a plan
    # written to a board it was not reconciled against duplicates the work on it.
    monkeypatch.setenv("CLICKUP_LIST_ID", "list-from-env")
    created, _ = _wire(monkeypatch)
    apply.apply_plan(_plan(), store=IdempotencyStore(tmp_path / "s.jsonl"),
                     when="2026-09-09")
    assert [c[1] for c in created] == ["list1"]


def test_a_click_with_no_store_of_its_own_writes_where_n8n_reads(monkeypatch, tmp_path):
    # Which file the store is, is the store's own question: WB_HOME, as the n8n nodes
    # resolve it. Apply holding a path of its own, derived from its own module's
    # location, is how a second checkout came to keep a second store.
    monkeypatch.setenv("WB_HOME", str(tmp_path))
    _wire(monkeypatch)
    apply.apply_plan(_plan(), when="2026-09-09")
    written = (tmp_path / "state" / "processed_effects.jsonl").read_text(encoding="utf-8")
    assert len(written.splitlines()) == 2


def test_a_plan_with_no_list_is_refused_rather_than_sent_to_the_environments(monkeypatch,
                                                                             tmp_path):
    monkeypatch.setenv("CLICKUP_LIST_ID", "list-from-env")
    created, commented = _wire(monkeypatch)
    with pytest.raises(WorkbenchError):
        apply.apply_plan(_plan(scope=""), store=IdempotencyStore(tmp_path / "s.jsonl"))
    assert created == [] and commented == []


def test_a_plan_with_nothing_to_apply_says_so(monkeypatch, tmp_path):
    _wire(monkeypatch)
    doubtful = dict(CREATE, confidence=0.4)
    with pytest.raises(WorkbenchError):
        apply.apply_plan(_plan([doubtful]), store=IdempotencyStore(tmp_path / "s.jsonl"))


def test_the_second_click_applies_nothing(monkeypatch, tmp_path):
    created, commented = _wire(monkeypatch)
    apply.apply_plan(_plan(), store=IdempotencyStore(tmp_path / "s.jsonl"),
                     when="2026-09-09")
    again = apply.apply_plan(_plan(), store=IdempotencyStore(tmp_path / "s.jsonl"),
                             when="2026-09-09")
    assert len(created) == 1 and len(commented) == 1     # no second call was made
    assert again["already_applied"] == 2
    assert again["created"] == 0 and again["commented"] == 0


def test_a_failure_is_not_a_skip_and_a_repeat_is_not_an_already_applied(monkeypatch,
                                                                        tmp_path):
    # One run holding one of each: a create the tracker refuses, a comment that goes
    # through, and a second point whose comment is the same effect. Counted the old way
    # the person read "skipped 1 already applied" for an effect the store had never seen,
    # and the refused create vanished from the counts altogether.
    created, commented = [], []
    monkeypatch.setattr(apply, "push_context", lambda: ([], {}, None))
    monkeypatch.setattr(apply, "push_one", lambda task, list_id, members, aliases, backlog: (
        created.append(task) or {"ok": False, "info": "no permission on that list",
                                 "assigned": False, "backlog": False}))
    monkeypatch.setattr(apply, "add_comment", lambda task_id, text: (
        commented.append(task_id) or (True, task_id)))
    path = tmp_path / "s.jsonl"
    summary = apply.apply_plan(_plan([CREATE, COMMENT, dict(COMMENT)]),
                               store=IdempotencyStore(path), when="2026-09-09")
    assert summary["created"] == 0 and summary["commented"] == 1
    assert summary["failed"] == ["no permission on that list"]
    assert summary["repeated"] == 1 and summary["already_applied"] == 0
    assert len(commented) == 1  # the repeat reached neither the tracker
    assert len(path.read_text(encoding="utf-8").splitlines()) == 1   # nor the store


def test_an_effect_is_keyed_on_its_point_exactly_as_it_was(monkeypatch, tmp_path):
    # The store is shared with the n8n workflow, which keys the point itself. If the
    # plan handed the key functions anything but the point, every effect already
    # applied would come back as new.
    import json

    _wire(monkeypatch)
    path = tmp_path / "s.jsonl"
    apply.apply_plan(_plan(), store=IdempotencyStore(path), when="2026-09-09")
    kept = {json.loads(line)["key"] for line in path.read_text(encoding="utf-8").splitlines()}
    assert kept == {create_key(CREATE), comment_key(COMMENT)}


def test_a_create_reaches_the_tracker_as_the_point_it_was_drafted_from(monkeypatch,
                                                                       tmp_path):
    created, _ = _wire(monkeypatch)
    apply.apply_plan(_plan([CREATE]), store=IdempotencyStore(tmp_path / "s.jsonl"),
                     when="2026-09-09")
    assert created[0][0] == CREATE


def test_a_backlog_create_still_goes_to_the_scope_list(monkeypatch, tmp_path):
    # A bug destined for the backlog is still written to the list this run belongs to —
    # push_one gets the scope list and no backlog id, so it only tags the task.
    created, _ = _wire(monkeypatch)
    monkeypatch.setattr(apply, "push_context", lambda: ([], {}, "backlog-list"))
    backlog = dict(CREATE, destination="backlog")
    apply.apply_plan(_plan([backlog]), store=IdempotencyStore(tmp_path / "s.jsonl"),
                     when="2026-09-09")
    assert [(c[1], c[2]) for c in created] == [("list1", None)]


def test_a_failed_effect_keeps_no_key_so_it_can_be_retried(monkeypatch, tmp_path):
    _wire(monkeypatch, create_ok=False)
    first = apply.apply_plan(_plan([CREATE]), store=IdempotencyStore(tmp_path / "s.jsonl"),
                             when="2026-09-09")
    assert first["failed"] == ["[Dev] New alerting"]
    created, _ = _wire(monkeypatch, create_ok=True)
    second = apply.apply_plan(_plan([CREATE]), store=IdempotencyStore(tmp_path / "s.jsonl"),
                              when="2026-09-09")
    assert [c[0]["name"] for c in created] == ["[Dev] New alerting"]
    assert second["created"] == 1


def test_a_network_error_on_a_comment_is_a_failed_effect_not_a_traceback(monkeypatch,
                                                                         tmp_path):
    # add_comment itself runs here, over a network that drops the second comment. The
    # click has to come back with a summary: that failure listed and left without a key,
    # so it can be retried, and every effect that went through keeping its key.
    import json
    from types import SimpleNamespace

    from src import clickup

    monkeypatch.setenv("CLICKUP_API_TOKEN", "pk_test")
    monkeypatch.setattr(apply, "push_context", lambda: ([], {}, None))
    monkeypatch.setattr(apply, "push_one", lambda task, list_id, members, aliases, backlog_id: {
        "ok": True, "info": task["name"], "assigned": False, "backlog": False})

    def post(url, **kwargs):
        if url.endswith("/task/86b/comment"):
            raise clickup.requests.ConnectionError("Connection reset by peer")
        return SimpleNamespace(status_code=200, text="")

    monkeypatch.setattr(clickup.requests, "post", post)
    comments = [{"name": f"C{i}", "detail": f"body {i}", "target_id": target,
                 "decision": "UPDATE", "confidence": 0.9, "reason": "r"}
                for i, target in enumerate(["86a", "86b", "86c"], 1)]
    path = tmp_path / "s.jsonl"
    summary = apply.apply_plan(_plan([CREATE] + comments),
                               store=IdempotencyStore(path), when="2026-09-09")

    assert summary["created"] == 1 and summary["commented"] == 2
    assert len(summary["failed"]) == 1 and "network error" in summary["failed"][0]
    kept = {json.loads(line)["key"] for line in path.read_text(encoding="utf-8").splitlines()}
    assert kept == {create_key(CREATE), comment_key(comments[0]), comment_key(comments[2])}


def test_the_comment_says_which_meeting_and_when():
    text = apply.comment_text(COMMENT, "Weekly sync", "2026-09-09")
    assert text.startswith('From the meeting "Weekly sync" (2026-09-09):')
    assert "provider fixed the sandbox" in text


def test_the_same_plan_on_another_day_is_still_a_no_op(monkeypatch, tmp_path):
    # The key must not carry the rendered comment: that text holds the meeting date, so
    # hashing it would give the same effect a new key tomorrow and comment twice.
    _wire(monkeypatch)
    apply.apply_plan(_plan([COMMENT]), store=IdempotencyStore(tmp_path / "s.jsonl"),
                     meeting_title="Weekly sync", when="2026-09-09")
    later = apply.apply_plan(_plan([COMMENT]), store=IdempotencyStore(tmp_path / "s.jsonl"),
                             meeting_title="Weekly sync", when="2026-09-10")
    assert later["already_applied"] == 1 and later["commented"] == 0


# --- the asks a person ticked -------------------------------------------------

DOUBTFUL_CREATE = dict(CREATE, name="Maybe new", confidence=0.4, reason="not sure")
DOUBTFUL_COMMENT = dict(COMMENT, name="Maybe the same", confidence=0.4, reason="torn")
ORPHAN = {"name": "No match", "affects": "the release", "kind": "other", "effect": "ask",
          "target_id": "", "confidence": 0.95, "reason": "nothing on the board"}


def test_a_ticked_ask_is_applied_as_the_agent_intended(monkeypatch, tmp_path):
    created, commented = _wire(monkeypatch)
    plan = _plan([DOUBTFUL_CREATE, DOUBTFUL_COMMENT])
    summary = apply.apply_plan(plan, plan.ask, store=IdempotencyStore(tmp_path / "s.jsonl"),
                               when="2026-09-09")
    assert [c[0]["name"] for c in created] == ["Maybe new"]
    assert [c[0] for c in commented] == ["86abc"]
    assert summary["created"] == 1 and summary["commented"] == 1


def test_an_ask_nobody_ticked_is_not_applied(monkeypatch, tmp_path):
    created, commented = _wire(monkeypatch)
    apply.apply_plan(_plan([CREATE, DOUBTFUL_COMMENT]),
                     store=IdempotencyStore(tmp_path / "s.jsonl"), when="2026-09-09")
    assert [c[0]["name"] for c in created] == ["[Dev] New alerting"] and commented == []


def test_a_ticked_ask_with_nothing_safe_to_do_writes_nothing(monkeypatch, tmp_path):
    # A meeting decision that matched no row cannot be commented anywhere and can never
    # be created; ticking it must not invent a task.
    created, commented = _wire(monkeypatch)
    plan = _plan([CREATE], meeting_decisions=[ORPHAN])
    apply.apply_plan(plan, plan.ask, store=IdempotencyStore(tmp_path / "s.jsonl"),
                     when="2026-09-09")
    assert [c[0]["name"] for c in created] == ["[Dev] New alerting"]
    assert commented == []


def test_a_confident_meeting_decision_is_applied_as_a_comment(monkeypatch, tmp_path):
    # The plan tab shows meeting decisions as comments; the button has to send them, or
    # the tab promises something that never happens.
    _, commented = _wire(monkeypatch)
    decision = dict(ORPHAN, name="Ship Wednesday, cut payments", effect="comment",
                    target_id="86def", confidence=0.9)
    summary = apply.apply_plan(_plan([], meeting_decisions=[decision]),
                               store=IdempotencyStore(tmp_path / "s.jsonl"),
                               meeting_title="Weekly sync", when="2026-09-09")
    assert [c[0] for c in commented] == ["86def"]
    assert summary["commented"] == 1
