"""The plan: what a run proposes to do to its scope, before anything is written.

One effect for every point — create a task, comment on an existing one, or ask a
person — built once from the matches and read by everyone: the Board plan tab and
`board_plan.md`, the caption and the checkboxes over the Apply button, `apply_plan`
itself, and the effect eval.

It used to be derived in five places, each with its own copy of the confidence gate;
two of them wrote their routing into the dicts they were handed, so a second build
read the first one's leavings and the eval had to deep-copy and un-stamp to replay
the same matches at another gate. The tab and the caption counted the same run
differently. Here the plan is one value: the builder touches nothing it is given,
and every consumer reads the same buckets and the same counts.

A plan carries the scope it was reconciled against, because the board a plan was
built on is the only board it may be written to.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from .idempotency import name_and_body

# The confidence gate: the confidence below which a match is not acted on without a
# person. One number, defined here with the routing it governs and imported wherever
# the gate is applied — the app, the CLI, the effect eval. The n8n IF nodes carry a
# literal 0.8 of their own; n8n/README.md says to keep them equal to this.
GATE = 0.8

# Where a point came from. A task can be created; a meeting decision changes work
# already under way and never can, which is the one routing difference between them.
# These are discriminators: what they are compared against, never what is shown.
TASK = "task"
MEETING_DECISION = "meeting decision"

# What each source is called on screen. Separate from the discriminator on purpose: the
# tag used to render the constant itself, so relabelling the display — "team decision",
# say — would have re-keyed the routing at the same time, and a run's effects would have
# changed because a word on a page did.
_SOURCE_LABELS = {TASK: "task", MEETING_DECISION: "meeting decision"}


def _source_label(source: str) -> str:
    """Display text for a source, derived from the discriminator but not it."""
    return _SOURCE_LABELS.get(source, source)


@dataclass(frozen=True)
class Effect:
    """What happens to one point, and everything a consumer needs to show or apply it.

    `intent` is the effect the agent would take if the gate were ignored, so a person
    ticking an `ask` says "do that" without the plan having to work out what "that" was.
    An ask with no intent has nothing safe to do and is handled by hand.
    """

    point: dict
    source: str
    # The effect kind: which of the three things this effect does. Not the point's own
    # `kind`, which on a meeting decision is what it changed — see `change_kind`.
    kind: str              # create | comment | ask
    intent: str            # create | comment | "" (nothing safe to do)
    target_id: str
    target_name: str
    confidence: float
    reason: str
    escalation_cause: str

    @property
    def name(self) -> str:
        """The point's name, read by the one definition the effect key reads it with."""
        return name_and_body(self.point)[0]

    @property
    def is_actionable(self) -> bool:
        """Whether there is anything safe to do with this point at all.

        An UPDATE naming no row on the board is the case: the agent knows the point
        changes existing work and cannot say which, so a person handles it by hand and
        no tick can turn it into an effect.
        """
        return bool(self.intent)


@dataclass(frozen=True)
class Plan:
    """One effect per point, the scope they would be written to, and the gate used.

    `board_read` says whether a board was read for this run at all, which is not the
    same fact as having a scope: a CLI run reconciles against a fixture it may not
    write to, and a board read and found empty is not a board nobody looked at.
    """

    scope: str
    gate: float
    board_size: int
    board_read: bool
    effects: tuple

    def _bucket(self, kind: str) -> tuple:
        return tuple(e for e in self.effects if e.kind == kind)

    @property
    def create(self) -> tuple:
        return self._bucket("create")

    @property
    def comment(self) -> tuple:
        return self._bucket("comment")

    @property
    def ask(self) -> tuple:
        return self._bucket("ask")

    @property
    def counts(self) -> dict:
        """The three numbers every screen shows, counted once so they cannot disagree."""
        return {"create": len(self.create), "comment": len(self.comment),
                "ask": len(self.ask)}

    def from_source(self, source: str) -> tuple:
        return tuple(e for e in self.effects if e.source == source)

    def with_approved(self, approved=()) -> "Plan":
        """This plan as a person left it: every ask they ticked becomes what the agent
        intended to do with it.

        Approving an ask means "do what you were going to do", and the plan is where
        what that was is written down. A caller working it out again from the intents
        is a second router, which is how the tab and the Apply button came to disagree.
        A tick on an ask with nothing safe to do changes nothing.
        """
        ticked = [e for e in approved if e.is_actionable]
        return replace(self, effects=tuple(
            replace(e, kind=e.intent) if e.kind == "ask" and e in ticked else e
            for e in self.effects))


def build_plan(
    task_matches: list,
    meeting_decision_matches: list,
    board: list,
    scope: str,
    gate: float = GATE,
    *,
    board_read: bool = True,
) -> Plan:
    """The plan for one run. Reads its inputs; writes to none of them.

    A plan is built from a board that was read, so `board_read` is true by default;
    a caller that read none -- the effect eval replaying saved matches -- says so.
    """
    names = {t.get("id", ""): t.get("name", "") for t in board}
    effects = [_task_effect(m, names, gate) for m in task_matches]
    effects += [_meeting_decision_effect(m, names, gate) for m in meeting_decision_matches]
    return Plan(scope=scope, gate=gate, board_size=len(board), board_read=board_read,
                effects=tuple(effects))


def _task_effect(match: dict, names: dict, gate: float) -> Effect:
    """A task below the gate asks; a confident UPDATE comments; a confident NEW creates."""
    confidence = match.get("confidence") or 0.0
    target_id = match.get("target_id") or ""
    if confidence < gate:
        kind = "ask"
        # What the agent would have done, so a person can approve it as it stands. An
        # UPDATE naming no row on the board leaves nothing safe to do.
        intent = "create" if match.get("decision") == "NEW" else (
            "comment" if target_id else "")
        # A guardrail has already said what went wrong; otherwise the agent simply was
        # not sure, which is the escalation the gate exists for.
        cause = match.get("escalation_cause") or "low_confidence"
    else:
        kind = intent = "comment" if match.get("decision") == "UPDATE" else "create"
        cause = ""
    return _effect(match, TASK, kind, intent, target_id, names, confidence, cause)


def _meeting_decision_effect(match: dict, names: dict, gate: float) -> Effect:
    """A meeting decision comments on the work it changes, or goes to a person.

    It never becomes new work: "ship Wednesday, cut payments" changes a commitment that
    already exists, so with no row to comment on there is nothing safe to do with it.
    """
    confidence = match.get("confidence") or 0.0
    target_id = match.get("target_id") or ""
    intent = "comment" if target_id else ""
    if intent and confidence >= gate:
        kind, cause = "comment", ""
    else:
        kind = "ask"
        # An orphan the agent was sure about did not go to a person for lack of
        # confidence, and saying so would misreport why it was escalated.
        cause = match.get("escalation_cause") or (
            "low_confidence" if confidence < gate else "")
    return _effect(match, MEETING_DECISION, kind, intent, target_id, names, confidence,
                   cause)


def _effect(point: dict, source: str, kind: str, intent: str, target_id: str,
            names: dict, confidence: float, cause: str) -> Effect:
    # The point is copied, not referenced: a consumer that writes into what it reads
    # would otherwise change the plan under everyone else.
    return Effect(
        point=dict(point),
        source=source,
        kind=kind,
        intent=intent,
        target_id=target_id,
        target_name=names.get(target_id, ""),
        confidence=confidence,
        reason=point.get("reason", ""),
        escalation_cause=cause,
    )


# --- the plan on screen -------------------------------------------------------


def target_label(effect: Effect) -> str:
    """The row a comment would land on, as the person checking it needs it: name and id."""
    return (f"`{effect.target_name}` (`{effect.target_id}`)" if effect.target_name
            else f"`{effect.target_id}`")


def change_kind(point: dict) -> str:
    """What a meeting decision changed: its scope, its date, its priority, or other.

    The point's own `kind`, which is not an effect kind (`create`/`comment`/`ask`) —
    and the two used to be read four lines apart, both spelled `kind`, so which one a
    reader was looking at depended on knowing which dict it came out of. The key is the
    extraction's output shape, so it stays; the word the code reads it by does not.
    """
    return str(point.get("kind") or "other")


def _tag(effect: Effect) -> str:
    """Where this point came from and, for a meeting decision, what it changed — in one
    backticked tag, empty when it says nothing.

    A merged list of effects hides where each one came from, and a meeting decision
    landing as a comment is a different thing from a task landing as one.
    """
    if effect.source == MEETING_DECISION:
        return f"`{_source_label(effect.source)} · {change_kind(effect.point)}`"
    bits = [str(effect.point.get(k, "")).lower() for k in ("type", "destination")]
    bits = [b for b in bits if b]
    return f"`{' → '.join(bits)}`" if bits else ""


def _line(effect: Effect) -> str:
    pieces = [f"- **{effect.name}**", _tag(effect)]
    if effect.kind == "comment":
        pieces.append(f"→ `{effect.target_name or effect.target_id}`")
    elif effect.kind == "ask":
        # Plain doubt is already on the line as the confidence; a guardrail firing is
        # the fact that is not.
        if effect.escalation_cause and effect.escalation_cause != "low_confidence":
            pieces.append(f"`{effect.escalation_cause}`")
        # A doubtful comment is shown with the row it would land on: that match is what
        # the person is asked to check. A doubtful create lands on no row.
        if effect.intent == "comment" and effect.target_id:
            pieces.append(f"→ proposed target {target_label(effect)}")
        pieces.append(f"(confidence {effect.confidence:.2f})")
    return " ".join(p for p in pieces if p) + f" — {effect.reason}"


def plan_markdown(plan: Plan) -> str:
    """The Board plan: what the run intends to do to its scope, before it does any of it."""
    lines = ["# Board plan", ""]
    if plan.board_size:
        lines += [f"Reconciled against {plan.board_size} open tasks on the board.", ""]
    elif plan.board_read:
        lines += ["The board has no open tasks, so every point is new by definition.", ""]
    else:
        # Nothing was read, so nothing is known about the board — which is not the same
        # fact as a board that was read and found empty.
        lines += ["No list was selected, so the board was not read — every point counts "
                  "as new.", ""]

    for kind, heading in (("create", "Create"), ("comment", "Comment on existing"),
                          ("ask", "Ask a human")):
        effects = plan._bucket(kind)
        lines += [f"## {heading} ({len(effects)})", ""]
        lines += [_line(e) for e in effects] or ["- nothing"]
        lines.append("")
    return "\n".join(lines)


def ask_label(effect: Effect) -> str:
    """What a person reads before ticking a doubtful call: what it would do, and where.

    A comment names the row it would land on, name and id — for a doubtful comment that
    match is the judgement being checked, and a label without it asks for a blind click.
    A create says it creates. With no safe action the label says so, and the caller shows
    it as needing manual handling. A guardrail cause is carried too: approving a phantom
    target without being told one fired is exactly the click this gate exists to prevent.
    """
    if not effect.is_actionable:
        action = "no safe action"
    elif effect.intent == "comment":
        action = f"comment on {target_label(effect)}"
    else:
        action = "create a new task"
    cause = (f" `{effect.escalation_cause}`"
             if effect.escalation_cause and effect.escalation_cause != "low_confidence"
             else "")
    return (f"{action} · **{effect.name}**{cause} — "
            f"{effect.reason} (confidence {effect.confidence:.2f})")
