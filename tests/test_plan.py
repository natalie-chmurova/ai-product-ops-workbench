"""The plan: one effect for every point, built once, carrying its scope.

The routing these tests pin is the rule the WB-39 brief states, not a reading of the
code: a task below the gate asks (cause `low_confidence` unless a guardrail already
named one); a confident UPDATE comments; a confident NEW creates. A meeting decision
never creates — it comments when it has a target and clears the gate, and otherwise
asks, with intent `comment` when it has a target and no intent when it has none.
"""

from __future__ import annotations

import copy
import re

import pytest

from src.plan import GATE, ask_label, build_plan, plan_markdown

BOARD = [
    {"id": "86abc", "name": "[Payments] Fix saved cards"},
    {"id": "86def", "name": "[Android] Crash on product detail"},
]


def task(**fields) -> dict:
    """A matched task, as `reconcile` hands it on."""
    return {"name": "New alerting", "detail": "alert on CDN errors", "decision": "NEW",
            "target_id": "", "confidence": 0.9, "reason": "nothing covers it",
            "escalation_cause": "", **fields}


def meeting_decision(**fields) -> dict:
    """A matched meeting decision, as `reconcile_decisions` hands it on."""
    return {"name": "Ship Wednesday, cut payments", "affects": "the release",
            "kind": "scope_change", "effect": "comment", "target_id": "86abc",
            "confidence": 0.9, "reason": "same release", **fields}


def one(plan) -> object:
    assert len(plan.effects) == 1
    return plan.effects[0]


# --- routing ------------------------------------------------------------------

@pytest.mark.parametrize("decision,target_id,confidence,kind,intent", [
    ("NEW", "", 0.9, "create", "create"),
    ("NEW", "", GATE, "create", "create"),          # the gate is a floor, not a fence
    ("UPDATE", "86abc", 0.9, "comment", "comment"),
    ("NEW", "", 0.5, "ask", "create"),
    ("UPDATE", "86abc", 0.5, "ask", "comment"),
    ("UPDATE", "", 0.0, "ask", ""),                 # no row to comment on: nothing safe
])
def test_a_task_is_routed_by_its_match_and_the_gate(decision, target_id, confidence,
                                                    kind, intent):
    effect = one(build_plan(
        [task(decision=decision, target_id=target_id, confidence=confidence)],
        [], BOARD, "list1"))
    assert (effect.kind, effect.intent) == (kind, intent)


@pytest.mark.parametrize("target_id,confidence,kind,intent", [
    ("86abc", 0.9, "comment", "comment"),
    ("86abc", 0.5, "ask", "comment"),
    ("", 0.9, "ask", ""),
    ("", 0.2, "ask", ""),
])
def test_a_meeting_decision_comments_or_asks_but_never_creates(target_id, confidence,
                                                               kind, intent):
    # A meeting decision changes work already under way, so "create a task" is not one
    # of its outcomes however sure the agent is.
    effect = one(build_plan(
        [], [meeting_decision(target_id=target_id, confidence=confidence,
                              effect="comment" if target_id else "ask")],
        BOARD, "list1"))
    assert (effect.kind, effect.intent) == (kind, intent)


def test_no_meeting_decision_ever_reaches_the_create_bucket():
    plan = build_plan([], [meeting_decision(confidence=c, target_id=t)
                           for c in (0.99, 0.3) for t in ("86abc", "")], BOARD, "list1")
    assert plan.counts["create"] == 0


def test_a_guardrail_cause_survives_the_gate():
    # An escalation a guardrail caused is a different event from an agent that reached
    # an answer and doubted it; counted as one, a broken run scores as a good one.
    unreadable = task(confidence=0.0, escalation_cause="unreadable")
    phantom = task(decision="UPDATE", target_id="", confidence=0.0,
                   escalation_cause="phantom_target")
    doubted = task(confidence=0.5)
    plan = build_plan([unreadable, phantom, doubted], [], BOARD, "list1")
    assert [e.escalation_cause for e in plan.ask] == [
        "unreadable", "phantom_target", "low_confidence"]


def test_an_effect_that_is_acted_on_has_no_escalation_cause():
    plan = build_plan([task(), task(decision="UPDATE", target_id="86abc")], [],
                      BOARD, "list1")
    assert [e.escalation_cause for e in plan.effects] == ["", ""]


def test_an_effect_names_the_row_it_would_land_on():
    effect = one(build_plan([task(decision="UPDATE", target_id="86def")], [],
                            BOARD, "list1"))
    assert (effect.target_id, effect.target_name) == (
        "86def", "[Android] Crash on product detail")


def test_an_effect_keeps_the_point_and_says_where_it_came_from():
    point, decision = task(), meeting_decision()
    plan = build_plan([point], [decision], BOARD, "list1")
    assert [e.source for e in plan.effects] == ["task", "meeting decision"]
    assert plan.effects[0].point == point and plan.effects[1].point == decision
    assert [e.name for e in plan.effects] == [point["name"], decision["name"]]


# --- the plan is a value ------------------------------------------------------

def test_the_plan_carries_the_scope_it_was_built_against():
    # Ruling: one scope per run — the board a plan was reconciled against is the board
    # it may be written to, and the plan is where that fact lives.
    assert build_plan([], [], BOARD, "list1").scope == "list1"


def test_building_a_plan_leaves_its_inputs_alone():
    # The app rebuilds the plan on every Streamlit rerun; a builder that writes into the
    # dicts it is handed makes the second build read the first one's leavings.
    tasks = [task(confidence=0.5), task(decision="UPDATE", target_id="86abc")]
    decisions = [meeting_decision(confidence=0.3)]
    board = copy.deepcopy(BOARD)
    before = copy.deepcopy((tasks, decisions, board))
    build_plan(tasks, decisions, board, "list1")
    assert (tasks, decisions, board) == before


def test_a_second_gate_reads_the_same_matches_afresh():
    # The effect eval replays saved matches at other gates. A cause stamped on the input
    # by the first pass would be read back as a fact about the reply by the second.
    tasks = [task(confidence=0.5)]
    build_plan(tasks, [], BOARD, "list1", 0.8)
    effect = one(build_plan(tasks, [], BOARD, "list1", 0.4))
    assert (effect.kind, effect.escalation_cause) == ("create", "")


def test_the_counts_cover_both_kinds_of_point():
    # The Board plan tab and the caption over the Apply button count one plan. While the
    # tab counted tasks alone and the caption counted both, one run read "ask a human 2"
    # in the tab and "ask a human 4" over the button.
    plan = build_plan(
        [task(), task(decision="UPDATE", target_id="86abc"), task(confidence=0.5)],
        [meeting_decision(), meeting_decision(confidence=0.2)],
        BOARD, "list1")
    assert plan.counts == {"create": 1, "comment": 2, "ask": 2}
    assert len(plan.effects) == 5
    assert [e.kind for e in plan.create] == ["create"]
    assert [e.kind for e in plan.comment] == ["comment", "comment"]
    assert [e.kind for e in plan.ask] == ["ask", "ask"]


def test_the_gate_is_defined_once_and_every_consumer_follows():
    # Five copies of 0.8 is how a threshold sweep ends up moving one of them.
    from evals.eval_effects import GATE as eval_gate

    import inspect

    assert eval_gate == GATE == 0.8
    assert inspect.signature(build_plan).parameters["gate"].default == GATE
    assert build_plan([], [], [], "list1").gate == GATE


# --- the plan on screen -------------------------------------------------------

def _bullets(md: str, heading: str) -> list:
    body = md.split(f"## {heading}")[1].split("\n## ")[0]
    return [line for line in body.splitlines() if line.startswith("- ")]


def _heading_count(md: str, heading: str) -> int:
    return int(re.search(rf"## {re.escape(heading)} \((\d+)\)", md).group(1))


HEADINGS = {"create": "Create", "comment": "Comment on existing", "ask": "Ask a human"}


def test_the_markdown_says_what_the_counts_say():
    plan = build_plan(
        [task(), task(decision="UPDATE", target_id="86abc"), task(confidence=0.5)],
        [meeting_decision(), meeting_decision(confidence=0.2)],
        BOARD, "list1")
    md = plan_markdown(plan)
    for bucket, heading in HEADINGS.items():
        assert _heading_count(md, heading) == plan.counts[bucket]
        assert len(_bullets(md, heading)) == plan.counts[bucket]


def test_the_plan_lists_every_point_once():
    plan = build_plan([task(), task(name="Saved cards update", decision="UPDATE",
                                    target_id="86abc"),
                       task(name="Unclear one", decision="UPDATE", target_id="86def",
                            confidence=0.4)],
                      [meeting_decision()], BOARD, "list1")
    md = plan_markdown(plan)
    for name in ("New alerting", "Saved cards update", "Unclear one",
                 "Ship Wednesday, cut payments"):
        assert md.count(name) == 1


def test_a_comment_names_the_row_it_lands_on():
    # A comment is only checkable if you can see which task it lands on.
    plan = build_plan([task(decision="UPDATE", target_id="86abc")], [], BOARD, "list1")
    assert "[Payments] Fix saved cards" in _bullets(plan_markdown(plan),
                                                    "Comment on existing")[0]


def test_a_meeting_decision_is_shown_as_one_in_the_same_section():
    plan = build_plan([task(decision="UPDATE", target_id="86def")],
                      [meeting_decision()], BOARD, "list1")
    lines = _bullets(plan_markdown(plan), "Comment on existing")
    line = next(line for line in lines if "Ship Wednesday" in line)
    assert "meeting decision" in line
    assert "scope_change" in line                       # what kind of decision it was
    assert "[Payments] Fix saved cards" in line         # the row it lands on


def test_a_doubtful_comment_shows_its_proposed_target():
    # The person asked is checking the match itself, so the row it would land on is
    # shown, by name and id.
    plan = build_plan([task(name="Unclear one", decision="UPDATE", target_id="86def",
                            confidence=0.4)], [], BOARD, "list1")
    line = _bullets(plan_markdown(plan), "Ask a human")[0]
    assert "[Android] Crash on product detail" in line and "86def" in line
    assert "0.40" in line


def test_a_doubtful_create_names_no_row():
    # A create lands on no existing task, even when the agent's reply named one.
    plan = build_plan([task(name="Maybe new", target_id="86abc", confidence=0.5)], [],
                      BOARD, "list1")
    line = _bullets(plan_markdown(plan), "Ask a human")[0]
    assert "86abc" not in line and "[Payments] Fix saved cards" not in line


def test_the_ask_section_tags_a_guardrail_cause_and_not_plain_doubt():
    plan = build_plan([task(name="Broken reply", confidence=0.0,
                            escalation_cause="unreadable"),
                       task(name="Unsure one", confidence=0.5)], [], BOARD, "list1")
    lines = _bullets(plan_markdown(plan), "Ask a human")
    assert "`unreadable`" in lines[0]
    assert "low_confidence" not in lines[1]   # the confidence is already on the line


def test_a_board_with_no_open_tasks_says_so():
    md = plan_markdown(build_plan([], [], [], "list1"))
    assert "no open tasks" in md.lower()


def test_a_board_that_was_not_read_says_so():
    # With nothing read, "the board has no open tasks" would be a claim about a board
    # this run never saw.
    md = plan_markdown(build_plan([task()], [], [], "", board_read=False)).lower()
    assert "no list was selected" in md
    assert "not read" in md
    assert "no open tasks" not in md


def test_a_board_read_and_found_empty_is_not_a_board_that_was_not_read():
    # Whether a board was read and where the plan may be written are two facts. A CLI
    # run against a fixture has no scope to write to and still read a board: saying it
    # was not read would contradict the line the run printed above the plan.
    md = plan_markdown(build_plan([task()], [], [], "", board_read=True)).lower()
    assert "no open tasks" in md
    assert "not read" not in md


def test_a_board_that_was_read_says_how_big_it_was():
    md = plan_markdown(build_plan([], [], BOARD, "list1"))
    assert "2 open tasks" in md


def test_an_empty_section_says_nothing_rather_than_going_blank():
    md = plan_markdown(build_plan([], [], BOARD, "list1"))
    for heading in HEADINGS.values():
        assert _bullets(md, heading) == ["- nothing"]


# --- what a person reads before ticking a doubtful call -----------------------

def test_a_doubtful_comment_label_names_the_row_it_would_land_on():
    # For a comment the target IS the judgement being checked; a label without it asks
    # for a blind click.
    effect = one(build_plan([task(name="Saved cards unblocked", decision="UPDATE",
                                  target_id="86def", confidence=0.62,
                                  reason="torn between two tasks")], [], BOARD, "list1"))
    label = ask_label(effect)
    assert "[Android] Crash on product detail" in label and "86def" in label
    assert "Saved cards unblocked" in label and "torn between two tasks" in label
    assert "0.62" in label


def test_a_doubtful_create_label_says_so_and_names_no_row():
    effect = one(build_plan([task(name="New alerting", target_id="86abc",
                                  confidence=0.5, reason="maybe new")], [],
                            BOARD, "list1"))
    label = ask_label(effect)
    assert "create a new task" in label
    assert "86abc" not in label and "[Payments] Fix saved cards" not in label


def test_a_label_with_no_safe_action_says_so():
    effect = one(build_plan([], [meeting_decision(name="No match", effect="ask",
                                                  target_id="", confidence=0.95,
                                                  reason="nothing on the board")],
                            BOARD, "list1"))
    assert ask_label(effect).startswith("no safe action")


def test_a_label_carries_the_cause_when_a_guardrail_fired():
    # The tab tags these; the checkbox is where the person actually decides, and a
    # phantom target is not something to approve without knowing it fired.
    effect = one(build_plan([task(decision="UPDATE", target_id="", confidence=0.0,
                                  escalation_cause="phantom_target",
                                  reason="matched a task that is not on the board")],
                            [], BOARD, "list1"))
    assert "phantom_target" in ask_label(effect)


def test_a_label_does_not_repeat_plain_doubt_as_a_cause():
    effect = one(build_plan([task(confidence=0.5)], [], BOARD, "list1"))
    label = ask_label(effect)
    assert "low_confidence" not in label and "0.50" in label


# --- a person's approval --------------------------------------------------------

def test_an_approved_ask_becomes_what_the_agent_intended():
    # Approving an ask means "do what you were going to do", and the plan says what that
    # was. Working it out again outside the plan is how two callers come to disagree.
    plan = build_plan([task(confidence=0.5), task(name="Saved cards", decision="UPDATE",
                                                  target_id="86abc", confidence=0.5)],
                      [], BOARD, "list1")
    assert plan.counts == {"create": 0, "comment": 0, "ask": 2}
    approved = plan.with_approved(plan.ask)
    assert approved.counts == {"create": 1, "comment": 1, "ask": 0}
    assert approved.create[0].name == "New alerting"
    assert approved.comment[0].target_id == "86abc"


def test_an_ask_nobody_ticked_stays_an_ask():
    plan = build_plan([task(confidence=0.5), task(name="Saved cards", confidence=0.5)],
                      [], BOARD, "list1")
    approved = plan.with_approved([plan.ask[0]])
    assert approved.counts == {"create": 1, "comment": 0, "ask": 1}
    assert approved.ask[0].name == "Saved cards"


def test_approving_an_ask_with_nothing_safe_to_do_does_not_act_on_it():
    # An UPDATE naming no row on the board has no effect to approve; a tick on it is a
    # person saying "yes" to a question the agent could not put.
    plan = build_plan([task(decision="UPDATE", target_id="", confidence=0.4)], [], BOARD,
                      "list1")
    assert one(plan).intent == ""
    approved = plan.with_approved(plan.ask)
    assert approved.counts == {"create": 0, "comment": 0, "ask": 1}


def test_approving_leaves_the_plan_it_was_given_alone():
    plan = build_plan([task(confidence=0.5)], [], BOARD, "list1")
    before = copy.deepcopy(plan.effects)
    plan.with_approved(plan.ask)
    assert plan.counts == {"create": 0, "comment": 0, "ask": 1}
    assert plan.effects == before
