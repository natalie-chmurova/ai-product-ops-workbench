"""Reconciling meeting points against the live board (pure logic, no API)."""

from src.reconcile import (
    board_summary,
    parse_decision,
    plan_markdown,
    reconcile,
    split_by_confidence,
)

BOARD = [
    {"id": "86abc", "name": "[Payments] Fix saved cards"},
    {"id": "86def", "name": "[Android] Crash on product detail"},
]


def test_board_summary_is_id_and_name():
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


# --- turning decisions into a plan of board effects ---

DECISIONS = [
    {"name": "New alerting", "decision": "NEW", "target_id": "", "confidence": 0.9, "reason": "r1"},
    {"name": "Saved cards update", "decision": "UPDATE", "target_id": "86abc",
     "confidence": 0.9, "reason": "r2"},
    {"name": "Unclear one", "decision": "UPDATE", "target_id": "86def",
     "confidence": 0.4, "reason": "torn between two"},
]


def test_split_by_confidence_routes_low_confidence_to_human():
    create, comment, ask = split_by_confidence(DECISIONS, threshold=0.8)
    assert [d["name"] for d in create] == ["New alerting"]
    assert [d["name"] for d in comment] == ["Saved cards update"]
    assert [d["name"] for d in ask] == ["Unclear one"]


def test_plan_lists_every_item_once():
    md = plan_markdown(DECISIONS, BOARD, threshold=0.8)
    for name in ("New alerting", "Saved cards update", "Unclear one"):
        assert md.count(name) == 1


def test_plan_names_the_target_task_for_comments():
    md = plan_markdown(DECISIONS, BOARD, threshold=0.8)
    # a comment is only actionable if you can see which task it lands on
    assert "[Payments] Fix saved cards" in md


def test_plan_on_empty_board_says_so():
    md = plan_markdown([], [], threshold=0.8)
    assert "no open tasks" in md.lower()


def test_reconcile_normalises_stage1_field_names():
    # stage 1 emits `what`/`context`; the plan and the comments need `name`.
    # Getting this wrong silently produced a plan full of blank titles.
    items = [{"what": "Diagnose search ranking", "owner": "Marco", "context": "over 3 words"}]
    out = reconcile(items, [])  # empty board -> no API call
    assert out[0]["name"] == "Diagnose search ranking"
    assert out[0]["detail"] == "over 3 words"
    assert out[0]["decision"] == "NEW"


def test_reconcile_on_empty_board_makes_no_decision_call():
    # nothing to match against means nothing to pay a model for
    out = reconcile([{"what": "anything"}], [])
    assert out[0]["confidence"] == 1.0
    assert "board is empty" in out[0]["reason"]
