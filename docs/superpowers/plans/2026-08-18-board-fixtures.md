# Board fixtures and the effect eval — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the board plan judgeable — give every transcript a board fixture representing the board as the run sees it, show the agent the fields it already reads, and score the effect the pipeline chooses for each meeting point.

**Architecture:** A fixture is a JSON file in the shape `get_tasks()` already returns, loaded through `load_board_fixture()` and selected with `workbench.py --board`. The live board stays the default. `board_summary()` starts rendering `status` / `owner` / `due` so the agent can reason about them. A new harness `evals/eval_effects.py` feeds `reconcile` the points straight from the ground truth — no extraction — and scores five effects, crediting an `ask` only when the escalation came from honest doubt rather than a guardrail firing.

**Tech Stack:** Python 3.9, pytest, `requests`, the Anthropic SDK via `src/client.py`. No new dependencies.

## Global Constraints

- **Spec:** `docs/superpowers/specs/2026-08-17-board-fixtures-design.md`. Read it before Task 1.
- **The live board stays the default.** A fixture is opt-in via `--board`; nothing may change what a flagless run does.
- **One change per measurement.** WB-21 (Task 1) is measured on its own, before anything in WB-20 touches agent behaviour.
- **Fixtures ship `"status": "DRAFT — awaiting Natallia's validation"`** and are used for no published number until she has read them.
- **No writes to the board.** The pipeline still stops at the plan; `add_comment` / `push_tasks` stay uncalled.
- **Model:** `claude-sonnet-5`, via `src/client.py`. Never pin a different one.
- **Every eval run costs money.** Use `--dry-run` while wiring; run the real thing once, deliberately.
- Existing tests must stay green: `python -m pytest -q` — 40 passing before this work starts.

---

## File Structure

**New:**
- `evals/board_messy_1.json` — the board as the messy-1 run sees it
- `evals/board_messy_2.json` — the board as the messy-2 run sees it
- `evals/board_demo.json` — the board as the demo run sees it (clean)
- `evals/board_demo_live_snapshot.json` — the same board with its real duplicates, captured and dated
- `evals/eval_effects.py` — the effect harness
- `evals/effect_results.md` — generated
- `tests/test_board_fixtures.py` — fixture loading, due-date mapping, richer summary, scoring

**Modified:**
- `evals/eval_decisions.py` — drop the prompt copy (Task 1)
- `src/clickup.py` — `due_date` in `get_tasks`, new `load_board_fixture`
- `src/reconcile.py` — richer `board_summary`, `escalation_cause`
- `workbench.py` — `--board`
- `evals/ground_truth*.json` — a `"board"` reference and `expected_effect` labels
- `evals/decision_results.md`, `docs/n8n-case.html` — re-measured numbers

---

## Task 1: Close the prompt drift, measure it alone (WB-21)

Do this first and finish it — including the re-measurement — before Task 2 changes what the agent sees. Two changes in one measurement cannot be told apart.

**Files:**
- Modify: `evals/eval_decisions.py:36-80`

**Interfaces:**
- Consumes: `load_prompt` from `src/client.py` — `load_prompt(name: str) -> str`, reads `prompts/<name>.md`.
- Produces: nothing other tasks depend on.

- [ ] **Step 1: Confirm the drift is real before changing anything**

```bash
cd "/Users/nchmurova/Job Search/ai-product-ops-workbench"
diff <(sed -n '43,67p' evals/eval_decisions.py) prompts/match.md
```

Expected: the diff shows `prompts/match.md` carrying two rules the eval copy lacks — one about a decision the team reached being an UPDATE, one about work someone is already doing being an UPDATE. If the diff is empty, stop: the premise of this task is gone.

- [ ] **Step 2: Replace the copy with the shared prompt**

In `evals/eval_decisions.py`, change the import line:

```python
from src.client import ask, load_prompt  # noqa: E402
```

Delete the whole `MATCH_PROMPT = """..."""` block (the constant and its docstring comment `# Same instruction the n8n "Match agent" node uses, kept in sync on purpose.`), and change `decide()` to load the shared file:

```python
def decide(point: dict) -> tuple[str, str]:
    reply = ask(
        "You are a precise board-sync agent.",
        load_prompt("match").format(
            board=BOARD_TEXT, name=point["name"], detail=point["detail"]
        ),
        max_tokens=400,
    )
    decision = (re.search(r"DECISION:\s*(NEW|UPDATE)", reply, re.I) or [None, "NEW"])[1].upper()
    target = (re.search(r"TASK_ID:\s*([A-Za-z0-9]+)", reply, re.I) or [None, ""])[1]
    if target.upper() == "NONE" or target not in BOARD_IDS:
        target = ""
    return decision, target
```

- [ ] **Step 3: Verify the prompt still formats**

```bash
source .venv/bin/activate
python -c "
from src.client import load_prompt
p = load_prompt('match').format(board='T1 | thing', name='n', detail='d')
assert 'T1 | thing' in p and 'already doing' in p
print('formats, and carries the drifted-in rule')
"
```

Expected: `formats, and carries the drifted-in rule`. A `KeyError` here means `prompts/match.md` gained a stray `{`.

- [ ] **Step 4: Re-measure**

```bash
python evals/eval_decisions.py 3
```

Expected: three runs print `decision accuracy` / `target accuracy`, then an average. Record the numbers. They may drop below the published 100/100 — that is the finding, not a failure. The two added rules make the eval's four traps harder, not easier.

- [ ] **Step 5: Record the discontinuity in the results file**

`evals/decision_results.md` is regenerated by the script. Append a note to it (edit the file after the run):

```markdown
> **Not comparable with the 2026-07-21 run.** Until 2026-08-18 this harness used its
> own copy of the match prompt and had drifted from `prompts/match.md` by two rules —
> a decision the team reached is an UPDATE to the work it concerns, and work someone is
> already doing is an UPDATE rather than a second copy. The earlier 100% / 100%
> therefore measured an agent that shipped with rules the eval never gave it. This run
> uses the real prompt.
```

- [ ] **Step 6: Update the published figures**

```bash
grep -n "100%" docs/n8n-case.html | head -20
```

Wherever the decision-eval figures appear, replace them with the numbers from Step 4 and add one sentence saying the harness had drifted and the runs are not comparable. Do not touch the extraction-eval figures — this change does not affect them.

- [ ] **Step 7: Run the test suite**

```bash
python -m pytest -q
```

Expected: `40 passed`. This task touches no tested code, so a failure means something unrelated broke.

- [ ] **Step 8: Commit**

```bash
git add evals/eval_decisions.py evals/decision_results.md docs/n8n-case.html
git commit -m "The decision eval reads the shared prompt, then re-measure (WB-21)

The harness carried its own copy of the match prompt and had drifted from
prompts/match.md by two rules: a decision the team reached is an UPDATE to the
work it concerns, and work someone is already doing is an UPDATE rather than a
second copy. WB-11 made that file the single source precisely so the module,
the n8n node and this eval could not diverge; the eval never read it.

So the published 100/100 described an agent missing exactly the rules that
shipped. Re-measured on the real prompt, and the results file now says the two
runs are not comparable.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 2: Read the deadline, load a fixture

**Files:**
- Modify: `src/clickup.py:58-84`
- Create: `tests/test_board_fixtures.py`

**Interfaces:**
- Consumes: `WorkbenchError` from `src/client.py` (already imported in `src/clickup.py`).
- Produces:
  - `get_tasks(list_id=None, include_closed=False) -> list[dict]` — each dict now `{id, name, status, assignees, due_date}`; `due_date` is an ISO date string or `""`.
  - `load_board_fixture(path: str | Path) -> list[dict]` — same shape, read from a file.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_board_fixtures.py`:

```python
"""Board fixtures: a board read from a file instead of the live tracker."""

import json

import pytest

from src.clickup import load_board_fixture
from src.client import WorkbenchError

FIXTURE = {
    "transcript": "samples/transcript_messy_1.txt",
    "status": "DRAFT — awaiting Natallia's validation",
    "tasks": [
        {
            "id": "B1",
            "name": "[Release] Cut the August release",
            "status": "in progress",
            "assignees": ["Dana"],
            "due_date": "2026-08-19",
        }
    ],
}


def test_fixture_loads_in_the_shape_get_tasks_returns(tmp_path):
    path = tmp_path / "board.json"
    path.write_text(json.dumps(FIXTURE), encoding="utf-8")
    board = load_board_fixture(path)
    assert board == FIXTURE["tasks"]


def test_fixture_fills_in_missing_optional_fields(tmp_path):
    path = tmp_path / "board.json"
    path.write_text(json.dumps({"tasks": [{"id": "B1", "name": "Only the basics"}]}), encoding="utf-8")
    board = load_board_fixture(path)
    assert board == [
        {"id": "B1", "name": "Only the basics", "status": "", "assignees": [], "due_date": ""}
    ]


def test_missing_fixture_names_the_path(tmp_path):
    with pytest.raises(WorkbenchError) as exc:
        load_board_fixture(tmp_path / "nope.json")
    assert "nope.json" in str(exc.value)


def test_malformed_fixture_fails_loudly(tmp_path):
    path = tmp_path / "board.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(WorkbenchError):
        load_board_fixture(path)
```

- [ ] **Step 2: Run them to watch them fail**

```bash
source .venv/bin/activate
python -m pytest tests/test_board_fixtures.py -v
```

Expected: FAIL — `ImportError: cannot import name 'load_board_fixture'`.

- [ ] **Step 3: Add `due_date` to `get_tasks`**

In `src/clickup.py`, add to the imports at the top:

```python
import json
from datetime import datetime, timezone
from pathlib import Path
```

Then replace the task-building loop inside `get_tasks` (currently lines 74-84):

```python
    out = []
    for t in r.json().get("tasks", []):
        out.append(
            {
                "id": t.get("id", ""),
                "name": t.get("name", ""),
                "status": (t.get("status") or {}).get("status", ""),
                "assignees": [a.get("username", "") for a in t.get("assignees", [])],
                "due_date": _iso_date(t.get("due_date")),
            }
        )
    return out


def _iso_date(raw) -> str:
    """ClickUp returns a due date as epoch milliseconds, or null. We want a date.

    A deadline the agent cannot read is a deadline it cannot reason about — which is
    why "they said Thursday" currently goes nowhere near the board's own date.
    """
    if not raw:
        return ""
    try:
        seconds = int(raw) / 1000
    except (TypeError, ValueError):
        return ""
    return datetime.fromtimestamp(seconds, tz=timezone.utc).date().isoformat()
```

Also update the docstring's first line to `"""Read the board: open tasks in a list, as [{id, name, status, assignees, due_date}].`

- [ ] **Step 4: Add `load_board_fixture`**

Append to `src/clickup.py`:

```python
BOARD_FIELDS = {"status": "", "assignees": [], "due_date": ""}


def load_board_fixture(path) -> list[dict]:
    """Read a board from a file, in the same shape `get_tasks()` returns.

    A fixture is how a transcript gets a board that belongs to its own world. The
    live board is still the default everywhere; this is opt-in, because a demo that
    silently stopped writing to a real tracker would lose the thing that makes it
    worth showing.

    Unlike `get_tasks()`, a bad path raises. An unreadable fixture is a mistake in
    an argument someone typed, and reconciling against an empty board instead would
    quietly turn every point into new work.
    """
    path = Path(path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise WorkbenchError(f"Board fixture not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise WorkbenchError(f"Board fixture is not valid JSON: {path} ({exc})") from exc

    board = []
    for task in raw.get("tasks", []):
        filled = {"id": task.get("id", ""), "name": task.get("name", "")}
        for field, default in BOARD_FIELDS.items():
            filled[field] = task.get(field, default() if callable(default) else default)
        board.append(filled)
    return board
```

Note: `BOARD_FIELDS` holds a mutable `[]` as a default. Because each task gets a fresh dict and the list is never mutated in place, this is safe — but if a later task starts appending to `filled["assignees"]`, copy it first.

- [ ] **Step 5: Run the tests**

```bash
python -m pytest tests/test_board_fixtures.py -v
```

Expected: 4 passed.

- [ ] **Step 6: Check the live board still reads, now with dates**

```bash
python -c "
from dotenv import load_dotenv; load_dotenv()
from src.clickup import get_tasks
board = get_tasks()
print(f'{len(board)} tasks')
for t in board[:3]:
    print(' ', t['id'], '|', t['name'][:45], '| due:', t['due_date'] or '(none)')
" 2>&1 | grep -v Warning
```

Expected: 11 tasks, each printing a due date or `(none)`. This is the step that catches an epoch-conversion mistake — a unit test on invented data would not.

- [ ] **Step 7: Commit**

```bash
git add src/clickup.py tests/test_board_fixtures.py
git commit -m "Read a board from a file, and read the deadline from ClickUp

get_tasks now carries due_date (ClickUp hands it over as epoch milliseconds),
and load_board_fixture reads the same shape from disk. A fixture is how a
transcript gets a board from its own world: the live list holds only the demo
meeting's tasks, so the messy transcripts currently reconcile against a board
that shares not one task with what they discuss.

Unlike get_tasks, a bad fixture path raises rather than returning []. An empty
board is not a neutral fallback — it silently turns every point into new work.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 3: Show the agent what it already reads

**Files:**
- Modify: `src/reconcile.py:21-23`
- Modify: `tests/test_reconcile.py:20-25`
- Modify: `tests/test_board_fixtures.py` (append)

**Interfaces:**
- Consumes: board dicts from Task 2 — `{id, name, status, assignees, due_date}`.
- Produces: `board_summary(tasks: list[dict]) -> str`, one line per task, fields joined with `" | "`, empty fields omitted.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_board_fixtures.py`:

```python
from src.reconcile import board_summary

RICH_BOARD = [
    {
        "id": "B1",
        "name": "[Release] Cut the August release",
        "status": "in progress",
        "assignees": ["Dana"],
        "due_date": "2026-08-19",
    },
    {"id": "B2", "name": "Bare task", "status": "", "assignees": [], "due_date": ""},
    {
        "id": "B3",
        "name": "Shared task",
        "status": "to do",
        "assignees": ["Sam", "Marco"],
        "due_date": "",
    },
]


def test_summary_shows_status_owner_and_due():
    line = board_summary(RICH_BOARD).splitlines()[0]
    assert line == "B1 | [Release] Cut the August release | status: in progress | owner: Dana | due: 2026-08-19"


def test_summary_omits_empty_fields_entirely():
    line = board_summary(RICH_BOARD).splitlines()[1]
    assert line == "B2 | Bare task"


def test_summary_joins_several_assignees():
    line = board_summary(RICH_BOARD).splitlines()[2]
    assert line == "B3 | Shared task | status: to do | owner: Sam, Marco"
```

- [ ] **Step 2: Run them to watch them fail**

```bash
python -m pytest tests/test_board_fixtures.py -v -k summary
```

Expected: FAIL — the current `board_summary` renders only `id | name`, so the first assertion mismatches.

- [ ] **Step 3: Implement**

Replace `board_summary` in `src/reconcile.py`:

```python
def board_summary(tasks: list[dict]) -> str:
    """The board as the agent sees it: id, name, and whatever else the task carries.

    Status, owner and deadline are read from the tracker already — they were simply
    dropped before the agent saw them. That is why "they said it's done" and "that
    date slipped" had nothing to reason against: the agent could not check a status
    it was never shown.

    Empty fields are omitted rather than rendered as "none", so a sparse board stays
    readable and an old fixture with only id and name renders exactly as before.
    """
    lines = []
    for t in tasks:
        parts = [f"{t.get('id', '')} | {t.get('name', '')}"]
        if t.get("status"):
            parts.append(f"status: {t['status']}")
        owners = ", ".join(a for a in t.get("assignees", []) if a)
        if owners:
            parts.append(f"owner: {owners}")
        if t.get("due_date"):
            parts.append(f"due: {t['due_date']}")
        lines.append(" | ".join(parts))
    return "\n".join(lines)
```

- [ ] **Step 4: Run the tests**

```bash
python -m pytest tests/test_board_fixtures.py tests/test_reconcile.py -v
```

Expected: all pass. `test_board_summary_is_id_and_name` in `tests/test_reconcile.py` still passes unchanged — its board carries no status, assignees or due date, so every optional part is omitted and the old rendering is reproduced exactly. If it fails, the omission logic is wrong.

- [ ] **Step 5: Rename the now-misleading test**

In `tests/test_reconcile.py`, rename `test_board_summary_is_id_and_name` to `test_board_summary_falls_back_to_id_and_name` and add one line above the assertion:

```python
def test_board_summary_falls_back_to_id_and_name():
    # A board with no status, owner or deadline renders exactly as it always did.
    assert board_summary(BOARD) == "86abc | [Payments] Fix saved cards\n86def | [Android] Crash on product detail"
```

- [ ] **Step 6: Run the whole suite**

```bash
python -m pytest -q
```

Expected: `47 passed` (40 existing + 7 new).

- [ ] **Step 7: Commit**

```bash
git add src/reconcile.py tests/test_reconcile.py tests/test_board_fixtures.py
git commit -m "Show the agent the status, owner and deadline it already reads

get_tasks has returned status and assignees since WB-11, and now due_date too,
but board_summary threw all of it away and handed the agent id | name. So the
two rules about checking the board before trusting a claim had nothing to work
with: the agent cannot verify a status it was never shown.

Empty fields are omitted rather than printed as none, which also means a board
carrying only id and name renders exactly as it did before.

This changes what the agent sees, so both eval harnesses need re-measuring and
numbers taken before it are not comparable.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 4: Say why an escalation happened

**Files:**
- Modify: `src/reconcile.py:26-71` (`parse_decision`), `src/reconcile.py:138-152` (`split_by_confidence`)
- Modify: `tests/test_board_fixtures.py` (append)

**Interfaces:**
- Consumes: nothing new.
- Produces:
  - `parse_decision(reply, board) -> dict` — now also `"escalation_cause"`, one of `""`, `"unreadable"`, `"phantom_target"`.
  - `split_by_confidence(decisions, threshold=0.8) -> tuple` — stamps `"low_confidence"` on any escalated decision whose cause is still `""`.

**Why the cause is split across two functions:** `parse_decision` can only see the two failures — an unreadable reply, a target that is not on the board. Whether honest doubt counts as an escalation depends on the threshold, and the threshold lives at the gate. So the parser reports what broke, and the gate labels the rest.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_board_fixtures.py`:

```python
from src.reconcile import parse_decision, split_by_confidence

SMALL_BOARD = [{"id": "86abc", "name": "[Payments] Fix saved cards"}]


def test_unreadable_reply_is_named_as_such():
    d = parse_decision("the model rambled instead of answering", SMALL_BOARD)
    assert d["escalation_cause"] == "unreadable"
    assert d["confidence"] == 0.0


def test_update_naming_a_task_not_on_the_board():
    reply = "DECISION: UPDATE\nTASK_ID: 99zzz\nCONFIDENCE: 0.9\nREASON: same work"
    d = parse_decision(reply, SMALL_BOARD)
    assert d["escalation_cause"] == "phantom_target"
    assert d["confidence"] == 0.0


def test_an_honest_answer_has_no_failure_cause():
    reply = "DECISION: UPDATE\nTASK_ID: 86abc\nCONFIDENCE: 0.9\nREASON: same work"
    d = parse_decision(reply, SMALL_BOARD)
    assert d["escalation_cause"] == ""


def test_the_gate_labels_honest_doubt():
    doubtful = {"name": "x", "decision": "NEW", "target_id": "", "confidence": 0.5, "escalation_cause": ""}
    broken = {"name": "y", "decision": "UPDATE", "target_id": "", "confidence": 0.0, "escalation_cause": "unreadable"}
    _, _, ask = split_by_confidence([doubtful, broken])
    assert [d["escalation_cause"] for d in ask] == ["low_confidence", "unreadable"]


def test_the_gate_does_not_relabel_a_confident_decision():
    confident = {"name": "z", "decision": "NEW", "target_id": "", "confidence": 0.95, "escalation_cause": ""}
    create, _, ask = split_by_confidence([confident])
    assert not ask
    assert create[0]["escalation_cause"] == ""
```

- [ ] **Step 2: Run them to watch them fail**

```bash
python -m pytest tests/test_board_fixtures.py -v -k "cause or gate"
```

Expected: FAIL — `KeyError: 'escalation_cause'`.

- [ ] **Step 3: Have the parser name what broke**

In `src/reconcile.py`, inside `parse_decision`, after the `unparseable` line and before the reason block, add:

```python
    if unparseable:
        cause = "unreadable"
    elif decision == "UPDATE" and not target:
        cause = "phantom_target"
    else:
        cause = ""
```

and add the field to the returned dict:

```python
    return {
        "decision": decision,
        "target_id": target,
        "confidence": confidence,
        "reason": reason,
        "escalation_cause": cause,
    }
```

Extend the docstring with a sentence:

```
    The two ways this can go wrong are reported as `escalation_cause`, because an
    escalation caused by a guardrail firing is not the same event as an agent that
    reached an answer and honestly doubted it — and scored as one, a broken run
    reads as a good one.
```

- [ ] **Step 4: Have the gate label honest doubt**

Replace the loop in `split_by_confidence`:

```python
    create, comment, ask = [], [], []
    for d in decisions:
        if d.get("confidence", 0) < threshold:
            # A guardrail already said what went wrong; otherwise the agent simply
            # was not sure, which is the escalation we actually want to see.
            if not d.get("escalation_cause"):
                d["escalation_cause"] = "low_confidence"
            ask.append(d)
        elif d.get("decision") == "UPDATE":
            comment.append(d)
        else:
            create.append(d)
    return create, comment, ask
```

- [ ] **Step 5: Run the tests**

```bash
python -m pytest tests/test_board_fixtures.py tests/test_reconcile.py -v
```

Expected: all pass — the existing `parse_decision` tests assert individual keys, not the whole dict, so the extra field does not disturb them.

- [ ] **Step 6: Show the cause in the plan's escalation lines**

In `src/reconcile.py`, in `plan_markdown`, replace the "Ask a human" loop body:

```python
    for d in ask:
        cause = d.get("escalation_cause", "")
        tag = f" `{cause}`" if cause and cause != "low_confidence" else ""
        lines.append(
            f"- **{d.get('name','')}**{tag} (confidence {d.get('confidence',0):.2f}) — {d.get('reason','')}"
        )
```

Honest doubt is the ordinary case and needs no tag; a guardrail firing is worth naming in the document a human reads.

- [ ] **Step 7: Run the whole suite**

```bash
python -m pytest -q
```

Expected: `52 passed`.

- [ ] **Step 8: Commit**

```bash
git add src/reconcile.py tests/test_board_fixtures.py
git commit -m "Escalations record why they happened, not just that they did

An ask is not a decision the agent makes — it is what happens when confidence
falls below the gate, whatever the cause. Scored naively it becomes the effect
that flatters the metric: an item expecting an escalation counts as correct
even when the agent escalated because its reply could not be parsed, or because
it named a task id absent from the board. Both are guardrails firing, and
crediting them reports a broken run as a good one.

parse_decision names the two failures it can see; the gate labels the rest
low_confidence, because whether doubt counts as an escalation depends on the
threshold and the threshold lives at the gate. The board plan now tags an
escalation caused by a guardrail, leaving honest doubt unmarked as the ordinary
case.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 5: `--board` on the CLI

**Files:**
- Modify: `workbench.py:34` (import), `:64` (`run` signature), `:93` (board read), `:114-123` (`main`)

**Interfaces:**
- Consumes: `load_board_fixture` from Task 2.
- Produces: `run(transcript_path: Path, board_path: Path | None = None) -> None`.

- [ ] **Step 1: Widen the import**

```python
from src.clickup import get_tasks, load_board_fixture
```

- [ ] **Step 2: Take the fixture as an argument**

Change the signature and the board read in `workbench.py`:

```python
def run(transcript_path: Path, board_path: Path | None = None) -> None:
```

and replace `board = get_tasks()` with:

```python
    # The live board is the default on purpose: the demo's worth is that it talks to
    # a real tracker. A fixture is how an eval transcript gets a board from its own
    # world, and it is always asked for explicitly.
    board = load_board_fixture(board_path) if board_path else get_tasks()
    if board_path:
        print(f"Board: fixture {board_path} ({len(board)} tasks)")
```

- [ ] **Step 3: Add the flag**

In `main()`:

```python
    parser.add_argument(
        "--board",
        type=Path,
        default=None,
        help="Reconcile against a board fixture file instead of the live ClickUp list",
    )
    args = parser.parse_args()
    try:
        run(args.transcript, args.board)
```

- [ ] **Step 4: Check the flag is wired without spending anything**

```bash
python workbench.py --help
```

Expected: the help text lists `--board`.

```bash
python workbench.py samples/transcript_messy_1.txt --board evals/nope.json
```

Expected: exits with `Error: Board fixture not found: evals/nope.json` and status 1 — `WorkbenchError` is already caught in `main`. Confirm no API call was made (the error appears before Stage 1 output).

- [ ] **Step 5: Commit**

```bash
git add workbench.py
git commit -m "workbench.py --board reconciles against a fixture

Opt-in, and only that: without the flag the run reads the live ClickUp list
exactly as before. A fixture that quietly replaced the live board would hollow
out the demo, whose value is that it writes to a real tracker.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 6: Draft the three fixtures and capture the cluttered board

Every file here is a **draft**. It carries a `status` field saying so, and no published number may use it until Natallia has read it.

**Files:**
- Create: `evals/board_messy_1.json`, `evals/board_messy_2.json`, `evals/board_demo.json`, `evals/board_demo_live_snapshot.json`

**Interfaces:**
- Consumes: `load_board_fixture` (Task 2).
- Produces: fixture files referenced by `"board"` in the ground truth (Task 7).

**How the drafts were derived.** A task belongs on the board when the transcript treats it as already existing — "we said we'd cut it Wednesday", "I'm on regression until Wednesday", "I was mostly in the search thing still". Dates come from the transcripts and are calendar-consistent: messy_1 is Monday 2026-08-17 (release Wednesday the 19th, Marco's diagnosis Thursday the 20th); messy_2 is the following Monday, 2026-08-24 (the incident "on Friday" is the 21st, the Thursday that slipped is the 20th).

**Side effect worth not losing.** The demo fixture's scenario — the same meeting processed twice — is literally the idempotency case, which until now has only ever been asked of the n8n path (WB-7). This fixture makes it answerable of the Python pipeline with no new scaffolding. Not built here; noted so the connection survives.

**A `scenario` field, and why it is not the same for every fixture.** For the messy transcripts the fixture is the board *before* that meeting — previous weeks' work. For demo it cannot be: nearly every task in that meeting is created *by* it, so a before-board would be almost empty and nothing could be commented on. The demo fixture therefore represents the board as it stands when that meeting is processed a second time — the re-processing case, and the one that proves a re-run comments instead of duplicating. Each file states which it is, because a fixture whose meaning has to be inferred will be read wrong.

- [ ] **Step 1: Write the messy-1 fixture**

```bash
cat > evals/board_messy_1.json <<'EOF'
{
  "transcript": "samples/transcript_messy_1.txt",
  "status": "DRAFT — awaiting Natallia's validation",
  "scenario": "The board before the meeting of Mon 2026-08-17. Work the transcript treats as already under way.",
  "note": "Deliberately absent: any tokenization task. The ground truth says to check whether one exists and create it if not, so putting one here would erase the case being measured.",
  "tasks": [
    {
      "id": "B1",
      "name": "[Release] Cut the August release",
      "status": "in progress",
      "assignees": ["Dana"],
      "due_date": "2026-08-19"
    },
    {
      "id": "B2",
      "name": "[Payments][QA] Regression testing on the payments flow",
      "status": "in progress",
      "assignees": ["Sam"],
      "due_date": "2026-08-19"
    },
    {
      "id": "B3",
      "name": "[Search] Improve search relevance ranking",
      "status": "in progress",
      "assignees": ["Marco"],
      "due_date": ""
    },
    {
      "id": "B4",
      "name": "[Design] Onboarding illustrations",
      "status": "to do",
      "assignees": ["Priya"],
      "due_date": ""
    }
  ]
}
EOF
python -c "
from src.clickup import load_board_fixture
print(len(load_board_fixture('evals/board_messy_1.json')), 'tasks load')"
```

Expected: `4 tasks load`.

- [ ] **Step 2: Write the messy-2 fixture**

```bash
cat > evals/board_messy_2.json <<'EOF'
{
  "transcript": "samples/transcript_messy_2.txt",
  "status": "DRAFT — awaiting Natallia's validation",
  "scenario": "The board before the standup of Mon 2026-08-24 — that is, after the previous week's meeting was processed.",
  "note": "B5 is the open question for review: the duplicated-notifications item was created unassigned last week, so this week's 'I'll take it after search' may be a comment plus an owner rather than a new task. The ground truth currently labels it must/new.",
  "tasks": [
    {
      "id": "B1",
      "name": "[Search] Diagnose search relevance ranking on long queries",
      "status": "in progress",
      "assignees": ["Marco"],
      "due_date": "2026-08-20"
    },
    {
      "id": "B2",
      "name": "[Payments][QA] Regression testing on the payments flow",
      "status": "in progress",
      "assignees": ["Sam"],
      "due_date": "2026-08-19"
    },
    {
      "id": "B3",
      "name": "[Payments] Wire up tokenization on our side",
      "status": "to do",
      "assignees": ["Marco"],
      "due_date": ""
    },
    {
      "id": "B4",
      "name": "[Design] Onboarding illustrations",
      "status": "in progress",
      "assignees": ["Priya"],
      "due_date": ""
    },
    {
      "id": "B5",
      "name": "[Notifications] Investigate duplicated push notifications",
      "status": "to do",
      "assignees": [],
      "due_date": ""
    }
  ]
}
EOF
python -c "
from src.clickup import load_board_fixture
print(len(load_board_fixture('evals/board_messy_2.json')), 'tasks load')"
```

Expected: `5 tasks load`.

- [ ] **Step 3: Write the demo fixture — the clean board**

These are the seven distinct pieces of work the demo meeting produces, with the duplicates removed.

```bash
cat > evals/board_demo.json <<'EOF'
{
  "transcript": "samples/transcript_demo.txt",
  "status": "DRAFT — awaiting Natallia's validation",
  "scenario": "The board as it stands when this meeting is processed a second time — the re-processing case. Unlike the messy fixtures this is not a before-board: almost every task here is created by this meeting, so a before-board would be empty and nothing could be commented on.",
  "note": "The same seven pieces of work as the live list, with its duplicates removed. Paired with board_demo_live_snapshot.json, which keeps them.",
  "tasks": [
    {
      "id": "T1",
      "name": "[Checkout][Dev] Resolve payment provider sandbox rejection for saved cards",
      "status": "in progress",
      "assignees": ["Marco"],
      "due_date": ""
    },
    {
      "id": "T2",
      "name": "[Checkout][Design] Finalize payment decline error state designs",
      "status": "in progress",
      "assignees": ["Priya"],
      "due_date": ""
    },
    {
      "id": "T3",
      "name": "[Checkout][Dev] Wire up detailed payment error states",
      "status": "to do",
      "assignees": ["Marco"],
      "due_date": ""
    },
    {
      "id": "T4",
      "name": "[Checkout][Product] Get decline copy reviewed by legal",
      "status": "to do",
      "assignees": ["Priya"],
      "due_date": ""
    },
    {
      "id": "T5",
      "name": "[Product Detail][Dev] Fix Android crash from null image carousel on empty-image products",
      "status": "to do",
      "assignees": ["Alex"],
      "due_date": ""
    },
    {
      "id": "T6",
      "name": "[Product Detail][QA] Regression cases for the empty-images path",
      "status": "to do",
      "assignees": ["Sam"],
      "due_date": ""
    },
    {
      "id": "T7",
      "name": "[Checkout][Product] Plan saved cards as fast-follow release",
      "status": "to do",
      "assignees": ["Dana"],
      "due_date": ""
    }
  ]
}
EOF
python -c "
from src.clickup import load_board_fixture
print(len(load_board_fixture('evals/board_demo.json')), 'tasks load')"
```

Expected: `7 tasks load`.

- [ ] **Step 4: Capture the cluttered board as it really is**

This is a capture, not a draft — do not hand-edit the task list it produces.

```bash
python - <<'EOF'
import json
from datetime import date
from dotenv import load_dotenv
load_dotenv()
from src.clickup import get_tasks

board = get_tasks()
out = {
    "transcript": "samples/transcript_demo.txt",
    "status": f"CAPTURED from the live ClickUp list on {date.today().isoformat()} — not hand-edited",
    "scenario": "The same board as board_demo.json, as it actually stands: with the duplicate tasks left by earlier test runs.",
    "note": "Committed because it contains the duplicates. They are the independent variable in the clutter measurement, not noise to tidy away. Do not clean this file.",
    "tasks": board,
}
with open("evals/board_demo_live_snapshot.json", "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=2)
print(f"captured {len(board)} tasks")
EOF
```

Expected: `captured 11 tasks`. If the count is not 11, the live board changed since 2026-08-17 — record the new count and say so in the eventual report rather than forcing the old number.

- [ ] **Step 5: Sanity-check the pair**

```bash
python -c "
from src.clickup import load_board_fixture
from src.reconcile import board_summary
clean = load_board_fixture('evals/board_demo.json')
dirty = load_board_fixture('evals/board_demo_live_snapshot.json')
print(f'clean {len(clean)} vs snapshot {len(dirty)}')
print(board_summary(clean).splitlines()[0])
print(board_summary(dirty).splitlines()[0])
"
```

Expected: `clean 7 vs snapshot 11`, and two rendered lines showing the richer format.

- [ ] **Step 6: Commit**

```bash
git add evals/board_messy_1.json evals/board_messy_2.json evals/board_demo.json evals/board_demo_live_snapshot.json
git commit -m "Draft a board fixture per transcript, and capture the cluttered one

A task goes on a fixture when the transcript treats it as already existing.
Dates come from the transcripts and are calendar-consistent: messy_1 is Monday
2026-08-17 with the release on Wednesday the 19th and Marco's diagnosis due
Thursday the 20th; messy_2 is the following Monday.

The demo fixture is deliberately not a before-board. Nearly every task in that
meeting is created by it, so a before-board would be empty and nothing could be
commented on; it represents the second processing of the same meeting instead,
which is exactly the case that proves a re-run comments rather than duplicates.
Each file says which it is.

The live snapshot keeps its duplicates on purpose — they are the variable being
measured. All three drafts await validation and back no published number yet.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 7: Label the expected effects

**Files:**
- Modify: `evals/ground_truth.json`, `evals/ground_truth_messy_1.json`, `evals/ground_truth_messy_2.json`

**Interfaces:**
- Produces: each ground truth gains `"board": "evals/board_<name>.json"`; each entry in `tasks` and `manager_notes` gains `"expected_effect"` from `create | comment | ask | verify_deadline | verify_status`.

**These labels are drafts too.** They encode a judgement about what should happen, which is Natallia's call. Draft them from her existing prose — `verdict` and `expected_effect` are already written out in the manager notes — and flag the ones the fixtures change.

- [ ] **Step 1: Add the board reference and effects to messy_1**

Edit `evals/ground_truth_messy_1.json`. Add after the `"status"` line:

```json
  "board": "evals/board_messy_1.json",
  "labels_status": "expected_effect DRAFT — derived from the prose verdicts, awaiting Natallia",
```

Then add `"expected_effect"` to each entry, per her existing prose:

- `manager_notes[0]` (ship Wednesday with payments cut) — prose says *"a comment on the existing release task"* → `"expected_effect": "comment"`, `"expected_target": "B1"`
- `manager_notes[1]` (Sam's regression) — prose says *"check the deadline on the board and, if it differs, leave a comment"* → `"expected_effect": "verify_deadline"`, `"expected_target": "B2"`
- `gt1` (search diagnosis) — a new task; the board's B3 is the broader relevance work, not the diagnosis → `"expected_effect": "create"`
- `gt3` (tokenization) — prose says *"Check whether this task already exists first. If not, create it"*, and the fixture deliberately has none → `"expected_effect": "create"`
- `gt5` (duplicated push notifications) → `"expected_effect": "create"`
- `gt6` (onboarding illustrations, `must: false`) — prose says *"the right effect is a deadline or a comment"*, and B4 exists → `"expected_effect": "comment"`, `"expected_target": "B4"`

- [ ] **Step 2: Add the board reference and effects to messy_2**

Edit `evals/ground_truth_messy_2.json` the same way, with `"board": "evals/board_messy_2.json"`:

- `manager_notes[0]` (diagnosis slipped from Thursday) → `"expected_effect": "verify_deadline"`, `"expected_target": "B1"`
- `manager_notes[1]` ("regression is done except one flaky test") — prose says *"check the task's status; if the developer hasn't moved it, notify the manager it can go to In Review; leave a comment about the still-failing test"* → `"expected_effect": "verify_status"`, `"expected_target": "B2"`
- `gt1` (tokenizer on hyphens) → `"expected_effect": "create"`
- `gt2` (price clipping) → `"expected_effect": "create"`
- `gt3` (flaky checkout test) → `"expected_effect": "create"`
- `gt4` (duplicated notifications carried over) → **`"expected_effect": "comment"`, `"expected_target": "B5"`, plus** `"review_note": "CHANGED BY THE FIXTURE — this was labelled a new task, but last week's meeting created it unassigned (B5). If that is right, the effect here is a comment plus an owner, not a second task. Natallia to confirm."`
- `gt5` (CDN alerting) → `"expected_effect": "create"`
- `gt6` (onboarding illustrations, `must: false`) → `"expected_effect": "comment"`, `"expected_target": "B4"`

- [ ] **Step 3: Add the board reference and effects to the clean set**

Edit `evals/ground_truth.json`, adding after the `"transcript"` line:

```json
  "board": "evals/board_demo.json",
  "labels_status": "expected_effect DRAFT — awaiting Natallia",
```

This set has no `manager_notes`, and every item is in `tasks`. Because the demo fixture is the re-processing case, six of the eleven already exist on it and expect a comment:

| item | summary | effect | target |
|---|---|---|---|
| `gt1` | chase the provider about sandbox rejection | `comment` | `T1` |
| `gt2` | finalize payment error-state designs | `comment` | `T2` |
| `gt3` | wire up the new payment error states | `comment` | `T3` |
| `gt4` | decline copy reviewed by legal | `comment` | `T4` |
| `gt5` | fix the Android empty-images crash | `comment` | `T5` |
| `gt6` | regression tests for the empty-images path | `comment` | `T6` |
| `gt7` | raise the Android device budget with finance | `create` | — |
| `gt8` | instrument checkout funnel analytics | `create` | — |
| `gt9` | search zero-results infinite spinner | `create` | — |
| `gt10` | write up the seller photo-nudge idea | `create` | — |
| `gt11` | ship checkout without saved cards, fast-follow | `comment` | `T7` |

`gt7` through `gt10` have no counterpart on the fixture, which is correct: the device budget, the analytics instrumentation, the spinner and the photo-nudge write-up are the four pieces of work this meeting raises that were never turned into tasks.

- [ ] **Step 4: Verify every file still parses and every reference resolves**

```bash
python - <<'EOF'
import json
from pathlib import Path
from src.clickup import load_board_fixture

for path in sorted(Path("evals").glob("ground_truth*.json")):
    if path.name == "match_ground_truth.json":
        continue
    gt = json.loads(path.read_text(encoding="utf-8"))
    board_ref = gt.get("board")
    print(f"{path.name}: board={board_ref}")
    assert board_ref, f"{path.name} has no board reference"
    ids = {t["id"] for t in load_board_fixture(board_ref)}
    entries = gt.get("tasks", []) + gt.get("manager_notes", [])
    for e in entries:
        effect = e.get("expected_effect")
        assert effect in {"create", "comment", "ask", "verify_deadline", "verify_status"}, \
            f"{path.name}: bad effect {effect!r}"
        target = e.get("expected_target")
        if effect in {"comment", "verify_deadline", "verify_status"}:
            assert target in ids, f"{path.name}: {effect} points at {target!r}, not on the board"
    print(f"  {len(entries)} entries labelled, all targets resolve")
EOF
```

Expected: three files listed, every target resolving. `match_ground_truth.json` is skipped — it belongs to the older decision eval and keeps its own inline board.

- [ ] **Step 5: Commit**

```bash
git add evals/ground_truth.json evals/ground_truth_messy_1.json evals/ground_truth_messy_2.json
git commit -m "Label the effect each meeting point should have on the board

Every ground truth now points at its fixture and says what should happen to
each item: create, comment, ask, verify_deadline or verify_status. The two
verify effects have no implementation — that is deliberate, and the eval will
report them as zero.

Most labels are transcriptions of prose verdicts already written during the
ground-truth validation. One is a real change, flagged for review: the
duplicated-notifications item in messy_2 was labelled a new task, but the
previous week's meeting created it unassigned, so the fixture makes a comment
plus an owner the likelier right answer. Marked in the file rather than decided
quietly.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 8: The effect eval

**Files:**
- Create: `evals/eval_effects.py`
- Modify: `tests/test_board_fixtures.py` (append)

**Interfaces:**
- Consumes: `reconcile` and `split_by_confidence` from `src/reconcile.py`; `load_board_fixture` from `src/clickup.py`. (`reconcile_decisions` is deliberately not used: decisions are scored through the same effect vocabulary as everything else, and it has only two outcomes of its own.)
- Produces: `score(entries: list[dict], decided: list[dict]) -> dict` — the pure scoring half, importable and testable without an API key.

- [ ] **Step 1: Write the failing scoring tests**

Append to `tests/test_board_fixtures.py`:

```python
from evals.eval_effects import score

def test_a_correct_comment_needs_the_right_target():
    entries = [
        {"id": "gt1", "expected_effect": "comment", "expected_target": "B1"},
        {"id": "gt2", "expected_effect": "comment", "expected_target": "B1"},
    ]
    decided = [
        {"id": "gt1", "effect": "comment", "target_id": "B1", "escalation_cause": ""},
        {"id": "gt2", "effect": "comment", "target_id": "B9", "escalation_cause": ""},
    ]
    result = score(entries, decided)
    assert result["effect_correct"] == 2       # both chose to comment
    assert result["target_correct"] == 1       # only one aimed correctly


def test_a_guardrail_escalation_is_not_a_correct_ask():
    entries = [
        {"id": "gt1", "expected_effect": "ask"},
        {"id": "gt2", "expected_effect": "ask"},
    ]
    decided = [
        {"id": "gt1", "effect": "ask", "target_id": "", "escalation_cause": "low_confidence"},
        {"id": "gt2", "effect": "ask", "target_id": "", "escalation_cause": "unreadable"},
    ]
    result = score(entries, decided)
    assert result["effect_correct"] == 1
    assert result["by_cause"]["unreadable"] == 1


def test_unimplemented_effects_score_zero():
    entries = [{"id": "n1", "expected_effect": "verify_deadline", "expected_target": "B2"}]
    decided = [{"id": "n1", "effect": "create", "target_id": "", "escalation_cause": ""}]
    result = score(entries, decided)
    assert result["effect_correct"] == 0
    assert result["per_effect"]["verify_deadline"] == {"total": 1, "correct": 0}
```

- [ ] **Step 2: Run them to watch them fail**

```bash
python -m pytest tests/test_board_fixtures.py -v -k "score or guardrail or unimplemented"
```

Expected: FAIL — `ModuleNotFoundError: No module named 'evals.eval_effects'`.

- [ ] **Step 3: Write the harness**

```bash
touch evals/__init__.py
```

Create `evals/eval_effects.py`:

```python
#!/usr/bin/env python3
"""Effect eval: given a board, what does the pipeline decide to DO with each point?

The extraction eval asks whether the work was found. This asks the next question —
create it, comment on what exists, or ask a human — which is the half of the SOP that
could not be measured while every transcript reconciled against the same unrelated
board.

It deliberately does NOT run extraction. Points come straight from the validated
ground truth, so an extraction miss and a routing miss stay separate numbers; folding
them together would hide which one to fix.

Five effects are scored:
  create · comment · ask · verify_deadline · verify_status

The last two have no implementation. They will score 0% until WB-9 and WB-18 land,
and that is the point of measuring them now.

An `ask` counts as correct only when it came from honest doubt. An escalation caused
by an unreadable reply or a target that is not on the board is a guardrail firing —
crediting it would report a broken run as a good one.

Usage:
  python evals/eval_effects.py               every labeled transcript
  python evals/eval_effects.py --only messy  only sets whose filename matches
  python evals/eval_effects.py --board evals/board_demo_live_snapshot.json --only ground_truth.json
                                             override the fixture (the clutter measurement)
  python evals/eval_effects.py --dry-run     list what would run, call no API
Writes: evals/effect_results.md
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(dotenv_path=ROOT / ".env")

from src.clickup import load_board_fixture  # noqa: E402
from src.reconcile import reconcile, split_by_confidence  # noqa: E402

EFFECTS = ("create", "comment", "ask", "verify_deadline", "verify_status")
UNIMPLEMENTED = ("verify_deadline", "verify_status")


def load_sets(only: str | None = None) -> list[dict]:
    """Every ground_truth*.json that names a board is one labeled transcript."""
    sets = []
    for path in sorted((ROOT / "evals").glob("ground_truth*.json")):
        if only and only.lower() not in path.name.lower():
            continue
        gt = json.loads(path.read_text(encoding="utf-8"))
        if not gt.get("board"):
            print(f"  skipping {path.name}: no board reference")
            continue
        entries = []
        for e in gt.get("tasks", []) + gt.get("manager_notes", []):
            entries.append(
                {
                    "id": e.get("id") or e.get("item", "")[:40],
                    "name": e.get("summary") or e.get("item", ""),
                    "detail": e.get("manager_note") or e.get("verdict", ""),
                    "expected_effect": e.get("expected_effect", ""),
                    "expected_target": e.get("expected_target", ""),
                }
            )
        sets.append(
            dict(
                name=path.name,
                label=gt.get("label", "clean"),
                board_ref=gt["board"],
                entries=[e for e in entries if e["expected_effect"]],
            )
        )
    return sets


def decide_all(entries: list[dict], board: list[dict]) -> list[dict]:
    """Route every point through the real reconciler and flatten to one effect each."""
    points = [{"what": e["name"], "context": e["detail"]} for e in entries]
    decisions = reconcile(points, board)
    create, comment, ask = split_by_confidence(decisions)
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


def score(entries: list[dict], decided: list[dict]) -> dict:
    """Compare intended effects with chosen ones. Pure — no API, no files."""
    by_id = {d["id"]: d for d in decided}
    per_effect = {e: {"total": 0, "correct": 0} for e in EFFECTS}
    by_cause: dict[str, int] = {}
    effect_correct = 0
    target_total = 0
    target_correct = 0
    misses = []

    for entry in entries:
        expected = entry["expected_effect"]
        got = by_id.get(entry["id"], {})
        chosen = got.get("effect", "")
        cause = got.get("escalation_cause", "")
        per_effect[expected]["total"] += 1

        if chosen == "ask":
            by_cause[cause or "low_confidence"] = by_cause.get(cause or "low_confidence", 0) + 1

        # An escalation caused by a guardrail is the mechanism failing safe, not the
        # agent correctly asking for help. Only honest doubt earns the credit.
        ok = chosen == expected
        if expected == "ask" and ok and cause not in ("", "low_confidence"):
            ok = False

        if ok:
            effect_correct += 1
            per_effect[expected]["correct"] += 1
        else:
            misses.append(
                {
                    "id": entry["id"],
                    "expected": expected,
                    "got": chosen or "(nothing)",
                    "cause": cause,
                    "intent": f"{got.get('decision','')} {got.get('target_id','') or 'NONE'}".strip(),
                    "reason": got.get("reason", ""),
                }
            )

        if entry.get("expected_target"):
            target_total += 1
            if got.get("target_id") == entry["expected_target"]:
                target_correct += 1

    return {
        "total": len(entries),
        "effect_correct": effect_correct,
        "target_total": target_total,
        "target_correct": target_correct,
        "per_effect": per_effect,
        "by_cause": by_cause,
        "misses": misses,
    }


def report(results: list[dict], board_override: str | None) -> str:
    lines = [
        f"# Effect eval (what the pipeline decides to DO) — {date.today().isoformat()}",
        "",
        "Points come from the validated ground truth, not from extraction: an extraction "
        "miss and a routing miss are different defects and are kept as different numbers.",
        "",
        "`verify_deadline` and `verify_status` have no implementation yet (WB-9, WB-18). "
        "They are measured anyway, and score zero, so the fix has something to move.",
        "",
        "An `ask` counts as correct only when it came from honest doubt. An escalation "
        "caused by an unreadable reply or a target absent from the board is a guardrail "
        "firing, and crediting it would report a broken run as a good one.",
        "",
    ]
    if board_override:
        lines += [f"**Board overridden for this run:** `{board_override}`", ""]

    lines += ["## Summary", "", "| transcript | board | points | effect accuracy | target accuracy |", "|---|---|---|---|---|"]
    for r in results:
        s, sc = r["set"], r["score"]
        acc = sc["effect_correct"] / sc["total"] if sc["total"] else 0.0
        tacc = sc["target_correct"] / sc["target_total"] if sc["target_total"] else None
        lines.append(
            f"| {s['label']} | `{r['board_ref']}` | {sc['total']} | {acc:.0%} | "
            + (f"{tacc:.0%} |" if tacc is not None else "— |")
        )

    for r in results:
        s, sc = r["set"], r["score"]
        lines += ["", f"## {s['label']}", "", "| expected effect | points | correct |", "|---|---|---|"]
        for effect in EFFECTS:
            row = sc["per_effect"][effect]
            if not row["total"]:
                continue
            note = " _(not implemented)_" if effect in UNIMPLEMENTED else ""
            lines.append(f"| `{effect}`{note} | {row['total']} | {row['correct']} |")
        if sc["by_cause"]:
            lines += ["", "Escalations by cause: " + ", ".join(f"`{k}` {v}" for k, v in sorted(sc["by_cause"].items()))]
        if sc["misses"]:
            lines += ["", "| point | expected | got | cause | agent's intent |", "|---|---|---|---|---|"]
            for m in sc["misses"]:
                lines.append(
                    f"| {m['id']} | `{m['expected']}` | `{m['got']}` | {m['cause'] or '—'} | {m['intent'] or '—'} |"
                )
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    args = sys.argv[1:]
    dry_run = "--dry-run" in args
    only = None
    board_override = None
    for i, a in enumerate(args):
        if a.startswith("--only"):
            only = a.split("=", 1)[1] if "=" in a else args[i + 1]
        if a.startswith("--board"):
            board_override = a.split("=", 1)[1] if "=" in a else args[i + 1]

    sets = load_sets(only)
    if not sets:
        raise SystemExit("no ground_truth*.json with a board reference found")

    if dry_run:
        print("DRY RUN — no API calls, nothing spent.\n")
        for s in sets:
            board = load_board_fixture(board_override or s["board_ref"])
            print(f"  {s['name']} ({s['label']})")
            print(f"    board  : {board_override or s['board_ref']} ({len(board)} tasks)")
            print(f"    points : {len(s['entries'])}")
            wanted: dict[str, int] = {}
            for e in s["entries"]:
                wanted[e["expected_effect"]] = wanted.get(e["expected_effect"], 0) + 1
            print(f"    expects: {', '.join(f'{k} {v}' for k, v in sorted(wanted.items()))}")
            print()
        print(f"model calls that would run: {sum(len(s['entries']) for s in sets)}")
        return

    results = []
    for s in sets:
        board = load_board_fixture(board_override or s["board_ref"])
        print(f"\n=== {s['label']} · board {board_override or s['board_ref']} ({len(board)} tasks) ===")
        decided = decide_all(s["entries"], board)
        sc = score(s["entries"], decided)
        acc = sc["effect_correct"] / sc["total"] if sc["total"] else 0.0
        print(f"  effect accuracy {acc:.0%} ({sc['effect_correct']}/{sc['total']})")
        if sc["by_cause"]:
            print(f"  escalations: {sc['by_cause']}")
        results.append(dict(set=s, score=sc, board_ref=board_override or s["board_ref"]))

    (ROOT / "evals" / "effect_results.md").write_text(report(results, board_override), encoding="utf-8")
    print("\nwritten: evals/effect_results.md")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the scoring tests**

```bash
python -m pytest tests/test_board_fixtures.py -v
```

Expected: all pass, including the three new scoring tests.

- [ ] **Step 5: Dry-run to see the shape without spending**

```bash
python evals/eval_effects.py --dry-run
```

Expected: three transcripts listed with their boards, point counts and expected-effect breakdowns, then the total number of model calls. Check that number before Step 6 — it is what the real run will cost.

- [ ] **Step 6: Run the whole suite**

```bash
python -m pytest -q
```

Expected: `55 passed`.

- [ ] **Step 7: Commit**

```bash
git add evals/eval_effects.py evals/__init__.py tests/test_board_fixtures.py
git commit -m "An eval for what the pipeline decides to DO with each point

The extraction eval asks whether the work was found; this asks the next
question — create, comment on existing, or ask a human. That half of the SOP
was unmeasurable while every transcript reconciled against the same unrelated
board.

Points come from the validated ground truth rather than from extraction, so an
extraction miss and a routing miss stay separate numbers. Five effects are
scored, two of which have no implementation and will report zero until WB-9 and
WB-18 land.

An ask counts only when it came from honest doubt: an escalation caused by an
unreadable reply or a phantom target is a guardrail firing, and the report
records what the agent was about to do so a right-target escalation is not
confused with a wrong-target one.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 9: Measure, and read the plans by eye

This is the task the whole plan exists for. It spends money — run each command once.

**Files:**
- Modify: `evals/effect_results.md`, `evals/results.md`, `evals/decision_results.md` (all generated)

- [ ] **Step 1: The effect eval on all three fixtures**

```bash
python evals/eval_effects.py
```

Expected: three sections, then `written: evals/effect_results.md`. `verify_deadline` and `verify_status` must show 0 correct — if either scores above zero, the scorer is wrong, because nothing implements them.

- [ ] **Step 2: The clutter measurement**

```bash
python evals/eval_effects.py --only ground_truth.json --board evals/board_demo_live_snapshot.json
```

Expected: the same points, same prompt, cluttered board. Record effect accuracy and the escalation counts, then compare with the clean-board numbers from Step 1. The difference is the cost of the duplicates.

Save both sets of numbers by hand into a short section at the end of `evals/effect_results.md`:

```markdown
## Board clutter, measured

Same transcript, same points, same prompt. Only the board differs.

| board | tasks | effect accuracy | escalations |
|---|---|---|---|
| `board_demo.json` (clean) | 7 | … | … |
| `board_demo_live_snapshot.json` (as it really is) | 11 | … | … |

The snapshot carries duplicate tasks left by earlier test runs: two near-identical
saved-cards tasks and three near-identical empty-images crash tasks.
```

- [ ] **Step 3: Re-measure the decision eval under the richer board summary**

```bash
python evals/eval_decisions.py 3
```

Its code is untouched since Task 1, so any change here belongs to `board_summary`. Append a line to `evals/decision_results.md` recording that, and what moved.

- [ ] **Step 4: Re-measure extraction, to prove it did not move**

```bash
python evals/run_eval.py 3
```

Expected: roughly `clean 100/100, messy-1 100/100, messy-2 100/100` — extraction never sees the board, so these numbers should not shift. A real change here means Task 3 leaked into a path it should not touch. Investigate before continuing.

- [ ] **Step 5: Read the plans by eye, on the fixtures**

```bash
python workbench.py samples/transcript_messy_1.txt --board evals/board_messy_1.json
cp outputs/board_plan.md /tmp/plan_messy1_fixture.md
python workbench.py samples/transcript_messy_2.txt --board evals/board_messy_2.json
cp outputs/board_plan.md /tmp/plan_messy2_fixture.md
python workbench.py samples/transcript_demo.txt --board evals/board_demo.json
cp outputs/board_plan.md /tmp/plan_demo_fixture.md
```

Then read all three. The specific thing to check: **"Comment on existing" must now be non-empty on the messy transcripts.** If it is still zero, the fixtures do not contain the work the meetings are about, and the fixture drafts — not the code — are what needs fixing.

- [ ] **Step 6: Commit the measurements**

```bash
git add evals/effect_results.md evals/decision_results.md evals/results.md
git commit -m "Measure: effects, board clutter, and the two evals under a richer board

First numbers for what the pipeline decides to DO, against boards that finally
belong to their transcripts' worlds. verify_deadline and verify_status report
zero as designed — the metric WB-9 and WB-18 will be measured against.

The clutter comparison holds everything constant but the board: the clean
fixture against a snapshot of the same board with the duplicates earlier test
runs left behind.

The decision eval is re-measured because board_summary changed under it; its
own code has not moved since the prompt-drift fix, so the delta belongs to that
one change. Extraction is re-measured only to confirm it did not move — it
never sees the board.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 10: Hand it back for validation

**Files:**
- Modify: `README.md`, `docs/n8n-case.html`

- [ ] **Step 1: Write the summary Natallia validates against**

Every number produced in Task 9 rests on drafts she has not read. Post a summary to WB-20 in Linear containing, in this order:

1. Effect accuracy per transcript, and the two zeros.
2. The clutter comparison, both rows.
3. What moved in the decision eval, and the statement that it belongs to `board_summary` alone.
4. **The open questions in the drafts**, each needing a yes or no:
   - messy_2 `gt4`: last week created the duplicated-notifications task unassigned, so is this week a comment plus an owner rather than a new task?
   - The demo fixture is the re-processing case, not a before-board. Is that the right thing to measure for that transcript?
   - messy_1: no tokenization task on the fixture, so `gt3` expects a create. Right?
5. That no number leaves the repo until she answers.

- [ ] **Step 2: Update the README's eval section**

Add the effect eval alongside the two existing harnesses — one paragraph, with the honest note that two of its five effects score zero by design.

- [ ] **Step 3: Hold the case study**

Do **not** update `docs/n8n-case.html` with effect numbers yet. It is the public page, and these numbers rest on unvalidated drafts. Only the WB-21 correction from Task 1 goes public before validation.

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "README: the effect eval, and what it does not yet prove

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

- [ ] **Step 5: Open the PR**

```bash
git push -u origin nattta26/wb-19-board-fixtures
gh pr create --base main --title "Board fixtures and the effect eval (WB-20, WB-21)" --body "See docs/superpowers/specs/2026-08-17-board-fixtures-design.md and docs/superpowers/plans/2026-08-18-board-fixtures.md.

Fixtures and effect labels are DRAFT pending validation; no number here is published outside the repo yet.

🤖 Generated with [Claude Code](https://claude.com/claude-code)"
```

---

## Notes for whoever executes this

- **Task 1 stands alone.** Finish it, including its re-measurement and commit, before starting Task 2. Its whole value is that its number is attributable.
- **The unit tests here run on invented dicts.** WB-11 shipped a bug they would not have caught — `reconcile` returned `what` while the plan read `name`, so every heading rendered blank. That is why Tasks 2, 6 and 9 each end with a run against real data.
- **If a fixture makes a ground-truth label look wrong, say so in the file** and carry on. Do not quietly relabel: the labels are the manager's judgement, and a fixture that rewrites them without asking recreates the exact problem the DRAFT convention exists to prevent.
