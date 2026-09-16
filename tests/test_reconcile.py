"""Reconciling meeting points against the live board (pure logic, no API)."""

from src.reconcile import (
    board_summary,
    parse_decision,
    reconcile,
    reconcile_decisions,
)

BOARD = [
    {"id": "86abc", "name": "[Payments] Fix saved cards"},
    {"id": "86def", "name": "[Android] Crash on product detail"},
]


def test_board_summary_falls_back_to_id_and_name():
    # A board with no status, owner or deadline renders exactly as it always did.
    assert board_summary(BOARD) == "86abc | [Payments] Fix saved cards\n86def | [Android] Crash on product detail"


def test_board_summary_empty_board():
    assert board_summary([]) == ""


def test_parse_decision_update():
    reply = (
        "DECISION: UPDATE\n"
        "TASK_ID: 86abc\n"
        "CONFIDENCE: 0.9\n"
        "REASON: same saved-cards work"
    )
    d = parse_decision(reply, BOARD)
    assert d["decision"] == "UPDATE"
    assert d["target_id"] == "86abc"
    assert d["confidence"] == 0.9
    assert d["reason"] == "same saved-cards work"


def test_parse_decision_new_has_no_target():
    reply = "DECISION: NEW\nTASK_ID: NONE\nCONFIDENCE: 0.8\nREASON: nothing covers it"
    d = parse_decision(reply, BOARD)
    assert d["decision"] == "NEW"
    assert d["target_id"] == ""


def test_update_pointing_off_board_loses_confidence():
    # the same guardrail the n8n workflow uses: an UPDATE must name a task that
    # actually exists, otherwise it is not trustworthy and goes to a human
    reply = "DECISION: UPDATE\nTASK_ID: 86zzz\nCONFIDENCE: 0.95\nREASON: invented id"
    d = parse_decision(reply, BOARD)
    assert d["target_id"] == ""
    assert d["confidence"] == 0.0


def test_garbage_reply_defaults_to_new_and_zero_confidence():
    d = parse_decision("the model rambled instead of answering", BOARD)
    assert d["decision"] == "NEW"
    assert d["confidence"] == 0.0


def test_escalation_always_carries_a_reason():
    # a human seeing "confidence 0.00 —" with no explanation cannot act on it
    d = parse_decision("the model rambled instead of answering", BOARD)
    assert d["reason"], "an escalated item must say why it was escalated"
    assert "could not read" in d["reason"]


def test_off_board_update_explains_itself():
    d = parse_decision("DECISION: UPDATE\nTASK_ID: 86zzz\nCONFIDENCE: 0.9\nREASON:", BOARD)
    assert "not on the board" in d["reason"]


# --- matching a point to the board ---


def test_reconcile_normalises_stage1_field_names():
    # stage 1 emits `what`/`context`; the plan and the comments need `name`.
    # Getting this wrong silently produced a plan full of blank titles.
    items = [{"what": "Diagnose search ranking", "owner": "Marco", "context": "over 3 words"}]
    out = reconcile(items, [])  # empty board -> no API call
    assert out[0]["name"] == "Diagnose search ranking"
    assert out[0]["detail"] == "over 3 words"
    assert out[0]["decision"] == "NEW"


def test_decisions_never_become_new_work():
    # a decision changes existing work; "create a task" is not a valid outcome
    out = reconcile_decisions([{"what": "Ship Wednesday, cut payments", "affects": "the release"}], [])
    assert out[0]["effect"] == "ask"          # no board -> a human looks at it
    assert "create" not in str(out).lower() or out[0]["effect"] != "create"


def test_reconcile_on_empty_board_makes_no_decision_call():
    # nothing to match against means nothing to pay a model for
    out = reconcile([{"what": "anything"}], [])
    assert out[0]["confidence"] == 1.0
    assert "board is empty" in out[0]["reason"]


def test_reconcile_accepts_a_generated_task():
    # The plan is about what gets created — a ClickUp-ready task — so both the CLI and
    # the app reconcile tasks, not raw action items. A task carries name/description.
    task = {"name": "[Search][Dev] Diagnose ranking", "description": "Goal:\nfind out",
            "owner": "Marco", "priority": 1, "tags": ["search"], "type": "bug",
            "destination": "sprint"}
    out = reconcile([task], [])  # empty board -> no model call
    assert out[0]["name"] == task["name"]
    assert out[0]["detail"] == task["description"]
    assert out[0]["decision"] == "NEW"
    assert out[0]["type"] == "bug" and out[0]["destination"] == "sprint"
