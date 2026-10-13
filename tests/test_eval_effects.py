"""The effect eval routes its points through the plan, and its numbers stay comparable.

`evals/eval_effects.py` used to flatten saved matches with its own copy of the routing:
a deep copy of every match, the previous pass's `low_confidence` stamp wiped off it,
`split_by_confidence` called, and the buckets mapped back by `id()`. All of that existed
because the router wrote into the dicts it was given. It reads the plan now.

The published effect numbers were measured with the old code, so they only stay
comparable if the new path returns exactly what the old one returned. `_frozen_*` below
is that old code, copied here verbatim and run beside the new function on the same saved
matches at the same gate. It is a pin, not a spec: nothing else may call it, and it is
deleted when the numbers are next re-measured. Its own identifiers are left as they
stood — a verbatim copy that has been re-spelled is no longer a copy.
"""

from __future__ import annotations

import copy

import evals.eval_effects as eval_effects
from src.plan import GATE

# --- FROZEN: src/reconcile.py's split_by_confidence and the eval's effects_from, as
# --- they stood at cc7afe7, before the plan became one value. Do not edit; do not call
# --- from production code.


def _frozen_split_by_confidence(decisions: list, threshold: float) -> tuple:
    create, comment, ask = [], [], []
    for d in decisions:
        if d.get("confidence", 0) < threshold:
            if not d.get("escalation_cause"):
                d["escalation_cause"] = "low_confidence"
            ask.append(d)
        elif d.get("decision") == "UPDATE":
            comment.append(d)
        else:
            create.append(d)
    return create, comment, ask


def _frozen_effects_from(entries: list, decisions: list, threshold: float) -> list:
    decisions = copy.deepcopy(decisions)
    for d in decisions:
        if d.get("escalation_cause") == "low_confidence":
            d["escalation_cause"] = ""

    create, comment, ask = _frozen_split_by_confidence(decisions, threshold)
    effect_of = {id(d): "create" for d in create}
    effect_of.update({id(d): "comment" for d in comment})
    effect_of.update({id(d): "ask" for d in ask})

    out = []
    for entry, d in zip(entries, decisions):
        out.append(
            {
                "id": entry["id"],
                "effect": effect_of[id(d)],
                "target_id": d.get("target_id", ""),
                "confidence": d.get("confidence", 0.0),
                "escalation_cause": d.get("escalation_cause", ""),
                "decision": d.get("decision", ""),
                "reason": d.get("reason", ""),
            }
        )
    return out


# --- end FROZEN ---------------------------------------------------------------


def _entry(i: int, effect: str) -> dict:
    return {"id": f"gt{i}", "name": f"point {i}", "detail": "", "expected_effect": effect,
            "expected_target": "", "flagged": False}


def _match(name: str, new_or_update: str, target_id: str, confidence: float, cause: str = ""):
    """One saved match, shaped as `reconcile` writes it into effect_decisions.json."""
    return {"what": name, "context": "", "name": name, "detail": "", "decision": new_or_update,
            "target_id": target_id, "confidence": confidence, "reason": f"why {name}",
            "escalation_cause": cause}


# Every shape a saved match comes in: acted on, doubted, and both guardrails. The
# last two are what the file can hold from an older harness — a record with no cause
# field at all, and one still carrying a gate's own stamp.
MATCHES = [
    _match("confident new", "NEW", "", 0.95),
    _match("confident update", "UPDATE", "B1", 0.9),
    _match("exactly at the gate", "NEW", "", GATE),
    _match("doubted new", "NEW", "", 0.5),
    _match("doubted update", "UPDATE", "B1", 0.62),
    _match("unreadable reply", "NEW", "", 0.0, "unreadable"),
    _match("target off the board", "UPDATE", "", 0.0, "phantom_target"),
    _match("stamped by an earlier gate", "NEW", "", 0.85, "low_confidence"),
    {"what": "no cause field", "name": "no cause field", "detail": "", "decision": "NEW",
     "target_id": "", "confidence": 0.7, "reason": "an older record"},
]
ENTRIES = [_entry(i, "create") for i in range(len(MATCHES))]

# The gates the sweep reports on, and the one the published numbers were measured at.
THRESHOLDS = [round(0.50 + 0.05 * i, 2) for i in range(10)] + [GATE]


def test_the_eval_flattens_saved_matches_exactly_as_it_did_before():
    for threshold in THRESHOLDS:
        assert eval_effects.effects_from(ENTRIES, MATCHES, threshold) == \
            _frozen_effects_from(ENTRIES, MATCHES, threshold), f"at gate {threshold}"


def test_the_eval_defaults_to_the_one_gate():
    assert eval_effects.effects_from(ENTRIES, MATCHES) == \
        _frozen_effects_from(ENTRIES, MATCHES, GATE)


def test_scoring_at_a_gate_leaves_the_saved_matches_alone():
    # The sweep scores the same saved matches at ten gates in a row. A pass that wrote
    # its routing back into them would have the next gate read its leavings as a fact
    # about the agent's reply.
    before = copy.deepcopy(MATCHES)
    for threshold in THRESHOLDS:
        eval_effects.effects_from(ENTRIES, MATCHES, threshold)
    assert MATCHES == before
