"""Applying a plan: every effect once, keys only after success, comments carry context."""

from pathlib import Path

from src import apply
from src.idempotency import IdempotencyStore


def _wire(monkeypatch, create_ok=True, comment_ok=True):
    created, commented = [], []
    monkeypatch.setattr(apply, "push_context", lambda: ([], {}, None))
    monkeypatch.setattr(
        apply, "push_one",
        lambda task, list_id, members, aliases, backlog_id: (
            created.append(task["name"]) or
            {"ok": create_ok, "info": task["name"], "assigned": False, "backlog": False}
        ),
    )
    monkeypatch.setattr(
        apply, "add_comment",
        lambda task_id, text: (commented.append((task_id, text)) or (comment_ok, task_id)),
    )
    return created, commented


CREATE = [{"name": "[Dev] New alerting", "description": "Goal:\nalert on CDN errors"}]
COMMENT = [{"name": "Saved cards update", "detail": "provider fixed the sandbox",
            "target_id": "86abc", "decision": "UPDATE"}]


def test_a_plan_is_applied_and_counted(monkeypatch, tmp_path):
    created, commented = _wire(monkeypatch)
    store = IdempotencyStore(tmp_path / "s.jsonl")
    summary = apply.apply_plan(CREATE, COMMENT, "list1", store, meeting_title="Weekly sync",
                               when="2026-09-09")
    assert created == ["[Dev] New alerting"]
    assert commented[0][0] == "86abc"
    assert summary["created"] == 1 and summary["commented"] == 1 and summary["skipped"] == 0
    assert summary["total"] == 2


def test_the_second_click_applies_nothing(monkeypatch, tmp_path):
    created, commented = _wire(monkeypatch)
    store = IdempotencyStore(tmp_path / "s.jsonl")
    apply.apply_plan(CREATE, COMMENT, "list1", store, when="2026-09-09")
    again = apply.apply_plan(CREATE, COMMENT, "list1", IdempotencyStore(tmp_path / "s.jsonl"),
                             when="2026-09-09")
    assert len(created) == 1 and len(commented) == 1     # no second call was made
    assert again["skipped"] == 2 and again["created"] == 0 and again["commented"] == 0


def test_a_failed_effect_keeps_no_key_so_it_can_be_retried(monkeypatch, tmp_path):
    _wire(monkeypatch, create_ok=False)
    store = IdempotencyStore(tmp_path / "s.jsonl")
    first = apply.apply_plan(CREATE, [], "list1", store, when="2026-09-09")
    assert first["failed"] == ["[Dev] New alerting"]
    created, _ = _wire(monkeypatch, create_ok=True)
    second = apply.apply_plan(CREATE, [], "list1", IdempotencyStore(tmp_path / "s.jsonl"),
                              when="2026-09-09")
    assert created == ["[Dev] New alerting"] and second["created"] == 1


def test_the_comment_says_which_meeting_and_when():
    text = apply.comment_text(COMMENT[0], "Weekly sync", "2026-09-09")
    assert text.startswith('From the meeting "Weekly sync" (2026-09-09):')
    assert "provider fixed the sandbox" in text


def test_the_key_matches_the_n8n_spec():
    # NEW is keyed on name + " " + description; UPDATE on target + the item BODY. Those
    # are the two payloads the n8n Idempotency check node hashes, so the app and the
    # workflow share one store instead of two that disagree.
    from src.idempotency import effect_key
    assert apply.create_key(CREATE[0]) == effect_key(
        "NEW", "", "[Dev] New alerting Goal:\nalert on CDN errors")
    assert apply.comment_key(COMMENT[0]) == effect_key(
        "UPDATE", "86abc", "provider fixed the sandbox")


def test_the_same_plan_on_another_day_is_still_a_no_op(monkeypatch, tmp_path):
    # The key must not carry the rendered comment: that text holds the meeting date, so
    # hashing it would give the same effect a new key tomorrow and comment twice.
    _wire(monkeypatch)
    store = IdempotencyStore(tmp_path / "s.jsonl")
    apply.apply_plan([], COMMENT, "list1", store, meeting_title="Weekly sync",
                     when="2026-09-09")
    later = apply.apply_plan([], COMMENT, "list1", IdempotencyStore(tmp_path / "s.jsonl"),
                             meeting_title="Weekly sync", when="2026-09-10")
    assert later["skipped"] == 1 and later["commented"] == 0


# --- one plan over two shapes of decision ---

DECIDED_SURE = {"name": "Ship Wednesday, cut payments", "affects": "the release",
                "kind": "scope_change", "effect": "comment", "target_id": "86abc",
                "confidence": 0.9, "reason": "same release"}
DECIDED_UNSURE = {"name": "Something vague", "affects": "?", "kind": "other",
                  "effect": "comment", "target_id": "86abc", "confidence": 0.3,
                  "reason": "unsure"}


def test_a_confident_meeting_decision_is_applied_as_a_comment():
    # The plan tab shows decisions as comments; the button has to send them, or the tab
    # promises something that never happens.
    create, comment, ask = apply.as_effects([], [dict(DECIDED_SURE)])
    assert not create and not ask
    assert comment[0]["target_id"] == "86abc" and comment[0]["intent"] == "comment"


def test_an_unsure_meeting_decision_waits_for_a_person():
    create, comment, ask = apply.as_effects([], [dict(DECIDED_UNSURE)])
    assert not comment and ask[0]["intent"] == "comment"


def test_a_meeting_decision_can_never_become_a_new_task():
    orphan = {"name": "No match", "effect": "ask", "target_id": "", "confidence": 0.95}
    create, comment, ask = apply.as_effects([], [orphan])
    assert not create and not comment
    assert ask[0]["intent"] == ""     # nothing safe to do; a person handles it


def test_task_decisions_and_meeting_decisions_end_up_in_one_plan():
    task = {"name": "New alerting", "decision": "NEW", "target_id": "", "confidence": 0.9,
            "reason": "nothing covers it"}
    create, comment, ask = apply.as_effects([task], [dict(DECIDED_SURE)])
    assert [d["intent"] for d in create] == ["create"]
    assert [d["intent"] for d in comment] == ["comment"]
