"""The decision eval calls production's match step, not a copy of it.

`evals/eval_decisions.py` used to keep its own board text and its own reply
parser, both copied from `src/reconcile.py`; the copy already drifted once
(its prompt text, fixed in WB-21). This pins the eval to
`src.reconcile.decide_one` so the two cannot drift apart again: it patches
`ask` where `src/reconcile.py` looks it up, runs the eval's real per-point
call for every ground-truth point, and checks both what gets sent to the
model and how a reply is scored.

Building `evals/eval_decisions.py` calls `main()`, never module import, to do
its work: importing it must not touch the real `.env` or the real
`evals/decision_results.md`. See `_run_eval` below for how each test keeps
both out of harm's way.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import evals.eval_decisions as eval_decisions
import src.client as client_module

ROOT = Path(__file__).resolve().parent.parent

# Read independently of evals/eval_decisions.py's own copy of this file, so the
# expectations below aren't just the module restating itself.
GT = json.loads((ROOT / "evals" / "match_ground_truth.json").read_text(encoding="utf-8"))
MATCH_PROMPT = (ROOT / "prompts" / "match.md").read_text(encoding="utf-8")

SYSTEM = "You are a precise board-sync agent."
MAX_TOKENS = 400

# The board text the deleted BOARD_TEXT built, written out literally rather than
# produced by calling src.reconcile.board_summary — otherwise this test would only
# restate the code it is meant to check.
BOARD_TEXT = "\n".join(f"{t['id']} | {t['name']}" for t in GT["board"])


def _expected_prompt(point: dict) -> str:
    return MATCH_PROMPT.format(board=BOARD_TEXT, name=point["name"], detail=point["detail"])


def _well_formed_reply(point: dict) -> str:
    """A plausible model reply that encodes this point's own ground truth."""
    return (
        f"DECISION: {point['expected_decision']}\n"
        f"TASK_ID: {point['expected_target'] or 'NONE'}\n"
        "CONFIDENCE: 0.95\n"
        "REASON: matches ground truth for this test\n"
    )


def _forbid_real_api(monkeypatch):
    """However the eval reaches for the model, it must not construct a real client.

    This is the backstop for the RED run: before the eval is changed to call
    `src.reconcile.decide_one`, patching that seam alone does not intercept
    its own private `decide()`, which would otherwise fall through to a real
    Anthropic client.
    """

    def _boom(*a, **k):
        raise AssertionError(
            "a real Anthropic client was constructed — the eval did not go "
            "through the patched src.reconcile.ask seam"
        )

    monkeypatch.setattr(client_module, "_get_client", _boom)


def _run_eval(monkeypatch, tmp_path, reply_for):
    """Run evals/eval_decisions.py's main() for one run, with no network and no
    writes to the real repo.

    `reply_for(point)` supplies the canned reply for each ground-truth point, in
    the order `main()` iterates `GT["points"]`. Returns `(calls, report_text)`:
    every `(system, prompt, max_tokens)` sent through the seam `src/reconcile.py`
    looks `ask` up on, and the text that would have been written to
    `evals/decision_results.md`.
    """
    _forbid_real_api(monkeypatch)

    points = GT["points"]
    calls = []
    state = {"i": 0}

    def fake_ask(system, prompt, max_tokens=4000):
        calls.append((system, prompt, max_tokens))
        point = points[state["i"]]
        state["i"] += 1
        return reply_for(point)

    monkeypatch.setattr("src.reconcile.ask", fake_ask)
    monkeypatch.setattr(eval_decisions, "ROOT", tmp_path)
    (tmp_path / "evals").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(sys, "argv", ["eval_decisions.py", "1"])

    eval_decisions.main()

    report_text = (tmp_path / "evals" / "decision_results.md").read_text(encoding="utf-8")
    return calls, report_text


def test_eval_sends_the_production_system_prompt_and_max_tokens_for_every_point(monkeypatch, tmp_path):
    calls, _ = _run_eval(monkeypatch, tmp_path, _well_formed_reply)

    points = GT["points"]
    assert len(calls) == len(points)
    for (system, prompt, max_tokens), point in zip(calls, points):
        assert system == SYSTEM
        assert max_tokens == MAX_TOKENS
        assert prompt == _expected_prompt(point)


def test_eval_scores_a_target_not_on_the_board_as_empty(monkeypatch, tmp_path):
    # "[Checkout] Saved cards unblocked" is UPDATE -> T1 in the ground truth. The
    # agent still names a decision, but an id that is not on the board is not
    # trustworthy, so the eval must score the target as missing, not as T1.
    corrupted = "[Checkout] Saved cards unblocked"

    def reply_for(point):
        if point["name"] == corrupted:
            return "DECISION: UPDATE\nTASK_ID: T99_NOT_ON_BOARD\nCONFIDENCE: 0.9\nREASON: bogus id\n"
        return _well_formed_reply(point)

    _, report = _run_eval(monkeypatch, tmp_path, reply_for)

    # decision right (UPDATE), target wrongly named -> blanked: 6 true updates,
    # 1 of them now misses its target -> 5/6.
    assert "| 1 | 100% | 83% |" in report
    assert f"- {corrupted} (1/1 runs)" in report


def test_eval_scores_an_unparseable_reply_as_wrong(monkeypatch, tmp_path):
    # "[Checkout] Start wiring payment error states" is UPDATE -> T3. A reply the
    # parser cannot read at all must default to NEW, the same as the old parser did.
    corrupted = "[Checkout] Start wiring payment error states"

    def reply_for(point):
        if point["name"] == corrupted:
            return "the model rambled instead of answering in the expected format"
        return _well_formed_reply(point)

    _, report = _run_eval(monkeypatch, tmp_path, reply_for)

    # decision wrong (defaults to NEW, expected UPDATE) -> 9/10; that point was
    # also one of the 6 true updates, so target accuracy drops the same way: 5/6.
    assert "| 1 | 90% | 83% |" in report
    assert f"- {corrupted} (1/1 runs)" in report
