# M1 — Demo consistency — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the web app, the CLI and the n8n workflow tell one story — read the board the same way, show the plan, apply it once through a human click — and refresh the public demo to match.

**Architecture:** The app gains the CLI's stage 2.5 (board read before any model call, `reconcile` over the generated tasks, a Board plan tab) and an Apply button backed by a new `src/apply.py` that wraps every tracker effect in the existing `IdempotencyStore`. `get_tasks()` learns to fail loudly and to page. The confidence gate becomes one constant. n8n is brought back to the shared prompt by a script plus a parity test, its board summary is enriched to what the Python path shows, and its state path goes through `WB_HOME`. The demo page is regenerated from a fresh run.

**Tech Stack:** Python 3.9 (compatibility holds until M2), pytest, `requests`, Streamlit 1.50, the Anthropic SDK via `src/client.py`, n8n CLI (`npx n8n`). No new dependencies.

**Spec:** `docs/superpowers/specs/2026-09-09-reusable-pipeline-program-design.md`, section "M1 — Demo consistency".

## Global Constraints

- **No file in `prompts/` changes.** The measurement stop of 2026-08-20 stands; M1 copies `prompts/match.md` into n8n as it is.
- **No eval script runs.** Tasks 3, 4 and 6 each run the pipeline once on the demo transcript to check the result by eye (about ten model calls each, a few cents); nothing else calls the API.
- **Python 3.9-compatible code:** annotations may use `X | None` only because every module has `from __future__ import annotations`; no `match` statements, no `isinstance(x, A | B)`.
- **Model stays `claude-sonnet-5`** via `src/client.py`; never pin another.
- **Board rows keep the shape `{id, name, status, assignees, due_date}`.**
- **Nothing is applied to ClickUp without a click.** The CLI still stops at `outputs/board_plan.md`.
- **Tests stay green at every commit:** `python -m pytest -q` — 65 passing before this plan starts.
- **Commits:** sentence-case subject in the repository's existing style (no `feat:` prefixes), body explains why, trailer `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.
- **Branch:** `nattta26/wb-<n>-demo-consistency` once the Linear ticket exists; otherwise `nattta26/m1-demo-consistency`. One PR to `main` at the end.
- Run everything from the checkout with the project venv: `cd ~/Workbench && source .venv/bin/activate`.
- **Revised 2026-09-10 after review.** Four defects the review found are fixed inside these
  tasks rather than deferred: the scope was read from one list and applied to another (Task 3);
  meeting decisions were shown but never applied (Task 4); the comment key hashed the rendered
  text including `date.today()`, which both broke a second-day re-apply and disagreed with the
  key the n8n node computes (Task 4); `Mark processed` committed the whole fresh batch after one
  successful apply (Task 5).
- **One scope per run.** Whatever board a plan was reconciled against is the board it is applied
  to. Applying a plan to a different list is how duplicates get made, and it must be impossible
  rather than discouraged.

---

## File Structure

**New:**
- `src/apply.py` — turns a plan (create / comment buckets) into tracker effects, each guarded by the idempotency store; one responsibility, no Streamlit, no CLI.
- `scripts/__init__.py`, `scripts/sync_n8n_match_prompt.py` — writes `prompts/match.md` into the n8n Match agent node.
- `tests/test_clickup_read.py` — `get_tasks` failure and paging.
- `tests/test_clickup_write.py` — `push_one` routing, tags, assignee.
- `tests/test_apply.py` — apply once, skip on repeat, no key on failure, comment text.
- `tests/test_n8n_parity.py` — the n8n export carries the shared prompt, the rich summary, and `WB_HOME` paths.

**Modified:**
- `src/reconcile.py` — `GATE` constant; defaults use it.
- `evals/eval_effects.py` — imports `GATE` instead of defining it.
- `src/clickup.py` — `get_tasks` raises and pages; `_task_row`; `push_context`, `push_one`; `push_tasks` loops `push_one`.
- `workbench.py` — board read before stage 1; reconcile over tasks.
- `app.py` — board read before stage 1; stage 2.5; Board plan tab; Apply plan control replacing Send to ClickUp.
- `n8n/meeting-to-clickup-sync.workflow.json` — Match agent prompt, Board summary, store path.
- `n8n/README.md`, `docs/n8n-case.html`, `README.md`, `docs/index.html`, `tests/test_reconcile.py`.

---

## Task 1: One confidence gate

**Files:**
- Modify: `src/reconcile.py` (top of file; the three `threshold: float = 0.8` defaults)
- Modify: `evals/eval_effects.py:52-64` (import block and `GATE = 0.8`)
- Test: `tests/test_reconcile.py`

**Interfaces:**
- Produces: `src.reconcile.GATE: float = 0.8`, imported by Task 3 (app) and by `evals/eval_effects.py`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_reconcile.py`:

```python
# --- one gate, defined once ---

import inspect

from src.reconcile import GATE


def test_one_gate_everywhere():
    # The effect eval, the plan and the app must agree on where the gate is. Five
    # copies of 0.8 is how a threshold sweep ends up moving one of them.
    from evals.eval_effects import GATE as eval_gate

    assert eval_gate == GATE == 0.8
    for fn in (split_by_confidence, plan_markdown, decisions_markdown):
        assert inspect.signature(fn).parameters["threshold"].default == GATE
```

- [ ] **Step 2: Run it to see it fail**

Run: `python -m pytest tests/test_reconcile.py::test_one_gate_everywhere -q`
Expected: FAIL with `ImportError: cannot import name 'GATE' from 'src.reconcile'`.

- [ ] **Step 3: Define the constant and use it**

In `src/reconcile.py`, after the imports (after `from .client import ask, load_prompt`), add:

```python
# The confidence gate. One number, imported wherever the gate is applied — the plan,
# the app, the effect eval. The n8n IF nodes carry a literal 0.8 of their own;
# n8n/README.md says to keep them equal to this.
GATE = 0.8
```

Then change the three defaults — in `decisions_markdown`, `split_by_confidence` and `plan_markdown` — from `threshold: float = 0.8` to `threshold: float = GATE`.

In `evals/eval_effects.py`, change the import line

```python
from src.reconcile import reconcile, split_by_confidence  # noqa: E402
```
to
```python
from src.reconcile import GATE, reconcile, split_by_confidence  # noqa: E402
```
and delete the line `GATE = 0.8` below the path constants.

- [ ] **Step 4: Run the tests**

Run: `python -m pytest -q`
Expected: `66 passed`.

- [ ] **Step 5: Note the n8n literal**

Append to `n8n/README.md`:

```markdown
## The confidence gate

The two `Confident?` IF nodes compare against a literal `0.8`. The Python side keeps
the same number in `src.reconcile.GATE`; if one moves, move the other.
```

- [ ] **Step 6: Commit**

```bash
git add src/reconcile.py evals/eval_effects.py tests/test_reconcile.py n8n/README.md
git commit -m "One confidence gate, defined once

The 0.8 lived in five places: three defaults in reconcile, the effect eval's own
constant, and the n8n IF nodes. A threshold sweep that suggested 0.7 would have
moved one of them. The Python side now imports src.reconcile.GATE; n8n keeps its
literal and the README says to keep it equal.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

## Task 2: Reading the board fails loudly and reads every page

**Files:**
- Modify: `src/clickup.py:65-92` (`get_tasks`)
- Modify: `workbench.py:64-105` (`run`)
- Test: `tests/test_clickup_read.py` (new)

**Interfaces:**
- Produces: `get_tasks(list_id: str | None = None, include_closed: bool = False) -> list[dict]` — returns `[]` only when no list id is configured; raises `WorkbenchError` on any HTTP or network failure; concatenates every page. `_task_row(t: dict) -> dict` maps one ClickUp task to the board row shape.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_clickup_read.py`:

```python
"""Reading the board: unconfigured is empty, failing is an error, paged is complete."""

import pytest

from src import clickup
from src.client import WorkbenchError


class FakeResponse:
    def __init__(self, status: int, payload: dict | None = None, text: str = ""):
        self.status_code = status
        self._payload = payload or {}
        self.text = text

    def json(self) -> dict:
        return self._payload


def _task(i: int) -> dict:
    return {"id": f"t{i}", "name": f"Task {i}", "status": {"status": "to do"},
            "assignees": [], "due_date": None}


def test_unconfigured_board_is_empty_not_an_error(monkeypatch):
    monkeypatch.delenv("CLICKUP_LIST_ID", raising=False)
    assert clickup.get_tasks() == []


def test_a_failing_read_raises_instead_of_pretending_the_board_is_empty(monkeypatch):
    # An expired token used to return [] — and every meeting point became new work.
    monkeypatch.setenv("CLICKUP_API_TOKEN", "pk_test")
    monkeypatch.setattr(clickup.requests, "get",
                        lambda *a, **k: FakeResponse(401, text="Token invalid"))
    with pytest.raises(WorkbenchError) as exc:
        clickup.get_tasks("123")
    assert "401" in str(exc.value)
    assert "CLICKUP_API_TOKEN" in str(exc.value)


def test_every_page_is_read(monkeypatch):
    monkeypatch.setenv("CLICKUP_API_TOKEN", "pk_test")
    pages = {
        0: {"tasks": [_task(1), _task(2)], "last_page": False},
        1: {"tasks": [_task(3)], "last_page": True},
    }
    seen = []

    def fake_get(url, params=None, **kwargs):
        seen.append(params["page"])
        return FakeResponse(200, pages[params["page"]])

    monkeypatch.setattr(clickup.requests, "get", fake_get)
    board = clickup.get_tasks("123")
    assert [t["id"] for t in board] == ["t1", "t2", "t3"]
    assert seen == [0, 1]


def test_a_single_page_without_last_page_flag_still_stops(monkeypatch):
    monkeypatch.setenv("CLICKUP_API_TOKEN", "pk_test")
    monkeypatch.setattr(clickup.requests, "get",
                        lambda *a, **k: FakeResponse(200, {"tasks": [_task(1)]}))
    assert len(clickup.get_tasks("123")) == 1


def test_network_failure_is_a_workbench_error(monkeypatch):
    monkeypatch.setenv("CLICKUP_API_TOKEN", "pk_test")

    def boom(*a, **k):
        raise clickup.requests.ConnectionError("down")

    monkeypatch.setattr(clickup.requests, "get", boom)
    with pytest.raises(WorkbenchError):
        clickup.get_tasks("123")


def test_task_row_keeps_the_board_shape():
    row = clickup._task_row({"id": "a", "name": "n", "status": {"status": "in progress"},
                             "assignees": [{"username": "Dana"}], "due_date": "1787097600000"})
    assert row == {"id": "a", "name": "n", "status": "in progress",
                   "assignees": ["Dana"], "due_date": "2026-08-19"}
```

- [ ] **Step 2: Run them to see them fail**

Run: `python -m pytest tests/test_clickup_read.py -q`
Expected: the 401 test, the paging test and the network test FAIL (a `[]` comes back where an error was expected; `seen == [0]`); `_task_row` fails with `AttributeError`.

- [ ] **Step 3: Rewrite `get_tasks`**

Replace the whole `get_tasks` function in `src/clickup.py` with:

```python
def get_tasks(list_id: str | None = None, include_closed: bool = False) -> list[dict]:
    """Read the board: open tasks in a list, as [{id, name, status, assignees, due_date}].

    Two different absences, kept apart on purpose:
    - no list id configured -> [] — board-blind mode, and the callers say so out loud;
    - configured but failing -> WorkbenchError. A board that reads as empty because a
      token expired would turn every meeting point into new work, silently, which is
      the exact failure the whole reconcile stage exists to prevent.

    ClickUp hands tasks over a page at a time; every page is read.
    """
    list_id = list_id or os.environ.get("CLICKUP_LIST_ID")
    if not list_id:
        return []
    out: list[dict] = []
    page = 0
    while True:
        try:
            r = requests.get(
                f"{API}/list/{list_id}/task",
                params={"include_closed": "true" if include_closed else "false", "page": page},
                headers=_headers(),
                timeout=20,
            )
        except requests.RequestException as exc:
            raise WorkbenchError(f"Could not reach ClickUp to read the board: {exc}") from exc
        if r.status_code != 200:
            raise WorkbenchError(
                f"Could not read the ClickUp board (HTTP {r.status_code}): {r.text[:120]}\n"
                "  Check CLICKUP_API_TOKEN and CLICKUP_LIST_ID in your .env."
            )
        data = r.json()
        tasks = data.get("tasks", [])
        out.extend(_task_row(t) for t in tasks)
        if data.get("last_page", True) or not tasks:
            break
        page += 1
    return out


def _task_row(t: dict) -> dict:
    """One ClickUp task -> the board row every consumer expects."""
    return {
        "id": t.get("id", ""),
        "name": t.get("name", ""),
        "status": (t.get("status") or {}).get("status", ""),
        "assignees": [a.get("username", "") for a in t.get("assignees", [])],
        "due_date": _iso_date(t.get("due_date")),
    }
```

- [ ] **Step 4: Run the tests**

Run: `python -m pytest -q`
Expected: `72 passed`.

- [ ] **Step 5: Read the board before paying for a model call (CLI)**

In `workbench.py`, inside `run()`, replace the block

```python
    board = load_board_fixture(board_path) if board_path else None
    if board_path:
        print(f"Board: fixture {board_path} ({len(board)} tasks)")
```
with
```python
    # The board is read before any model call — a fixture path that is mistyped and a
    # token that has expired are both mistakes in the setup, and finding either after
    # two stages of extraction means paying for a run that was never going to finish.
    # The board is read before any model call — a fixture path that is mistyped and a
    # token that has expired are both mistakes in the setup, and finding either after
    # two stages of extraction means paying for a run that was never going to finish.
    board = load_board_fixture(board_path) if board_path else get_tasks()
    if board_path:
        print(f"Board: fixture {board_path} ({len(board)} tasks)")
    elif not os.environ.get("CLICKUP_LIST_ID"):
        print("Board: none configured — every point will count as new")
    else:
        # A configured list that is empty is not the same fact as no list at all, and
        # get_tasks returns [] for both. The caller knows which, because it knows
        # whether a list was configured; say the one that is true.
        print(f"Board: live ClickUp list ({len(board)} open tasks)"
              + ("" if board else " — empty, so every point counts as new"))
    if len(board) > MAX_BOARD:
        raise WorkbenchError(
            f"The board has {len(board)} open tasks; the ceiling is {MAX_BOARD}. "
            "Every meeting item is matched against the whole board in its own model call, "
            "so this run would be slow and expensive. Narrow the list, or raise MAX_BOARD "
            "in workbench.py once you have measured what it costs."
        )
```

`workbench.py` needs `import os` (it does not import it today) and, above `run()`:

```python
# One model call per meeting item, each carrying the whole board. Cost grows as
# items x board size, so a board this large stops the run instead of quietly spending.
MAX_BOARD = 200
```
and delete the later lines
```python
    if board is None:
        board = get_tasks()
```
(keep the `if board:` reconcile block that follows them).

- [ ] **Step 6: Check the CLI fails fast on a bad token, without spending**

```bash
CLICKUP_API_TOKEN=pk_wrong python workbench.py samples/transcript_demo.txt; echo "exit $?"
```
Expected: `Error: Could not read the ClickUp board (HTTP 401): …` and `exit 1`, printed before `Stage 1/3`. No model call was made.

- [ ] **Step 7: Commit**

```bash
git add src/clickup.py workbench.py tests/test_clickup_read.py
git commit -m "Reading the board fails loudly and reads every page

get_tasks returned [] on any non-200, and the pipeline went on as if the board
were empty — every meeting point became new work, which is the one failure the
reconcile stage exists to prevent. Not configured still returns [] and the callers
say so; configured but failing now raises with the status and a hint. Pages are
read to the end; ClickUp hands over a hundred at a time. The CLI reads the board
before stage 1, so a bad token costs nothing.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

## Task 3: Stage 2.5 in the app, one scope per run

**Files:**
- Modify: `workbench.py` (the reconcile block in `run`)
- Modify: `app.py` (imports; the `with left:` block; the `with right:` block; tabs)
- Test: `tests/test_reconcile.py`

**Interfaces:**
- Consumes: `src.reconcile.reconcile(items, board)`, `reconcile_decisions`, `plan_markdown`, `decisions_markdown`, `GATE` (Task 1); `get_tasks` raising `WorkbenchError` (Task 2).
- Produces: `st.session_state["result"]` carries `context`, `tasks`, `sprint`, `triage`, `speakers`, `board`, `decisions`, `decided`, `plan`, **`scope_id`**, **`scope_label`**, **`meeting_date`**. `st.session_state["scope_choice_id"]` holds the picker's current value, so Task 4 can tell a stale plan from a fresh one.

- [ ] **Step 1: Pin the contract the plan relies on**

Append to `tests/test_reconcile.py`:

```python
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
```

Run: `python -m pytest tests/test_reconcile.py -q`
Expected: PASS already — `reconcile` reads `name`/`description` first. The test exists so a later change cannot break the contract the app now depends on.

- [ ] **Step 2: The CLI reconciles the tasks**

In `workbench.py`, change

```python
        decisions = reconcile(context.get("action_items", []), board)
```
to
```python
        # The plan is about what would be created, and what gets created is a task —
        # so reconcile the ClickUp-ready list, not the raw action items. This also puts
        # extracted bugs through the board check, which the action items never did.
        decisions = reconcile(tasks, board)
```

- [ ] **Step 3: The scope is chosen before Generate, not at apply time**

This is the review's second finding. Reading the board from `CLICKUP_LIST_ID` and letting a
picker choose a different list at apply time means the plan is reconciled against one board
and written to another — every item looks new, and the run produces the duplicates the whole
reconcile stage exists to prevent.

In `app.py`, add to the imports:

```python
from datetime import date
```

Then, in the `with left:` block, insert this **above** the `col_a, col_b = st.columns([1, 1])` line:

```python
    # The board this plan is built against is the board it will be applied to. Choosing
    # the list afterwards is how a plan reconciled against one board gets written to
    # another — which is precisely the duplicate the reconcile stage exists to prevent.
    lists = _cached_lists() if os.environ.get("CLICKUP_API_TOKEN") else []
    default_id = os.environ.get("CLICKUP_LIST_ID", "")
    c_scope, c_date = st.columns([2, 1])
    if lists:
        labels = [f"{l['space']} / {l['name']}" for l in lists]
        ids = [l["id"] for l in lists]
        idx = ids.index(default_id) if default_id in ids else 0
        choice = c_scope.selectbox("ClickUp list — reconciled against, and applied to",
                                   labels, index=idx, key="clickup_list")
        scope_id, scope_label = ids[labels.index(choice)], choice
    else:
        scope_id, scope_label = default_id, "the list from .env"
        c_scope.caption("ClickUp list: the one from .env" if default_id
                        else "No ClickUp list configured — every point will count as new")
    st.session_state["scope_choice_id"] = scope_id
    # The date that goes into every comment is the date of the MEETING, not of the
    # click. It is also excluded from the idempotency key (Task 4), so re-applying the
    # same plan on another day stays a no-op.
    meeting_date = c_date.date_input("Meeting date", value=date.today(), key="meeting_date")
```

- [ ] **Step 4: Read that scope, reconcile, show the plan**

Extend the imports:

```python
from src.clickup import get_lists, get_tasks, push_tasks
from src.reconcile import (
    GATE,
    decisions_markdown,
    plan_markdown,
    reconcile,
    reconcile_decisions,
)
```

Replace the whole `if run:` block inside `with right:` with:

```python
    if run:
        try:
            started = time.monotonic()
            with st.status("Working through the transcript...", expanded=True) as status:
                # Read the board before any model call: a bad token fails here, for free.
                board = get_tasks(scope_id) if scope_id else []
                if not scope_id:
                    st.write("Board: no list selected — every point will count as new")
                else:
                    st.write(f"Board: {len(board)} open tasks in {scope_label}"
                             + ("" if board else " — empty, so every point counts as new"))
                roster = team_roster()
                if roster:
                    st.write(f"Team roster ({len(roster)}): {roster_line(roster)}")
                st.write("Stage 1/3 — understanding the transcript")
                context = extract_context(transcript, roster)
                st.write("Stage 2/3 — building tasks, sprint summary, bug triage, per-speaker notes")
                tasks = build_tasks(context)
                sprint_md = build_sprint_summary(context)
                triage_md = build_bug_triage(context)
                speakers_md = build_speaker_summary(context, transcript, roster)
                st.write(f"Stage 2.5/3 — reconciling against the board ({len(board)} tasks)")
                decisions = reconcile(tasks, board)
                decided = reconcile_decisions(context.get("decisions", []), board)
                plan_md = plan_markdown(decisions, board) + "\n" + decisions_markdown(decided, board)
                elapsed = time.monotonic() - started
                st.write(f"Stage 3/3 — done in {elapsed:.0f}s")
                status.update(label=f"Done ✓ · {elapsed:.0f}s", state="complete", expanded=False)
            st.session_state["result"] = {
                "context": context, "tasks": tasks, "sprint": sprint_md, "triage": triage_md,
                "speakers": speakers_md, "elapsed": elapsed,
                "board": board, "decisions": decisions, "decided": decided, "plan": plan_md,
                "scope_id": scope_id, "scope_label": scope_label,
                "meeting_date": meeting_date.isoformat(),
            }
            # A fresh plan means fresh choices for the items below the gate.
            for k in [k for k in st.session_state if str(k).startswith("ask_")]:
                del st.session_state[k]
        except (WorkbenchError, ValueError) as exc:
            st.session_state["result"] = None
            st.error(str(exc))
```

Replace the tabs block with:

```python
        tab_tasks, tab_plan, tab_sprint, tab_triage, tab_speakers = st.tabs(
            ["Tasks", "Board plan", "Sprint Summary", "Bug Triage", "By Speaker"]
        )
        with tab_tasks:
            render_tasks(result["tasks"])
        with tab_plan:
            # older results in session_state predate the plan
            st.markdown(result.get("plan") or "_Re-run to reconcile against the board._")
        with tab_sprint:
            st.markdown(result["sprint"])
        with tab_triage:
            st.markdown(result["triage"])
        with tab_speakers:
            st.markdown(result.get("speakers") or "_Re-run to generate the per-speaker view._")
```

Leave `render_clickup(result["tasks"])` in place for now; Task 4 replaces it.

- [ ] **Step 5: Compile and run the tests**

```bash
python -m py_compile app.py workbench.py && python -m pytest -q
```
Expected: no output from py_compile; `74 passed`.

- [ ] **Step 6: See it in the browser**

Start the app through the preview configuration `workbench-app` (`.claude/launch.json`), open it, and check the left column now carries the list picker and a meeting-date field **above** the Generate button. Click **Generate artifacts** with the built-in demo transcript. Expected: the status box names the chosen list and its task count, then a `Stage 2.5/3` line; the result has five tabs; the **Board plan** tab shows `# Board plan`, `## Create`, `## Comment on existing`, `## Ask a human`, `## Decisions` with task titles as headings. This spends about ten model calls.

- [ ] **Step 7: Commit**

```bash
git add app.py workbench.py tests/test_reconcile.py
git commit -m "The web app reads the board and shows the plan

The main demo never reconciled: app.py did not import reconcile, so every point
looked new and the README's apply gate described a path nobody was shown. The
app now reads the board before the first model call, runs stage 2.5 over the
generated tasks, and renders the same board plan the CLI writes, as a fifth tab.

The list is chosen before Generate rather than at apply time, and travels with
the result. Reading one board and writing to another would have produced exactly
the duplicates this stage exists to prevent.

Both paths reconcile tasks rather than raw action items: the plan is about what
would be created, and what gets created is a task. Extracted bugs go through the
board check for the first time.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 4: Apply the plan, once

**Files:**
- Modify: `src/clickup.py:166-244` (`push_tasks` becomes `push_context` + `push_one` + a loop)
- Create: `src/apply.py`
- Modify: `app.py` (replace `render_clickup` with `render_apply`)
- Test: `tests/test_clickup_write.py` (new), `tests/test_apply.py` (new)

**Interfaces:**
- Consumes: `IdempotencyStore`, `effect_key` from `src/idempotency.py` (unchanged); `add_comment`, `_create_task`, `list_url` from `src/clickup.py`; `split_by_confidence` (Task 1).
- Produces:
  - `push_context() -> tuple[list[dict], dict[str, str], str | None]` — members, alias map, backlog list id.
  - `push_one(task: dict, list_id: str, members: list[dict], aliases: dict[str, str], backlog_id: str | None) -> dict` — `{"ok": bool, "info": str, "assigned": bool, "backlog": bool}`.
  - `apply_plan(create: list[dict], comment: list[dict], list_id: str | None = None, store: IdempotencyStore | None = None, meeting_title: str = "", when: str | None = None) -> dict` — `{"created", "commented", "skipped", "assigned", "backlog", "failed": [...], "total", "list_url"}`. `when` is the **meeting's** date, supplied by the caller; it appears in the comment and never in the key.
  - `comment_body(item: dict) -> str`, `comment_text(item: dict, meeting_title: str, when: str) -> str`, `comment_key(item: dict) -> str`.
  - `as_effects(decisions: list[dict], decided: list[dict], threshold: float = GATE) -> tuple[list, list, list]` — `(create, comment, ask)` over task decisions **and** meeting decisions, each item stamped with `intent` ∈ `"create" | "comment" | ""`.

- [ ] **Step 1: Write the failing tests for `push_one`**

Create `tests/test_clickup_write.py`:

```python
"""Writing one task: owner, backlog routing, marker tags — no network."""

from src import clickup


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
```

Run: `python -m pytest tests/test_clickup_write.py -q`
Expected: FAIL with `AttributeError: module 'src.clickup' has no attribute 'push_one'`.

- [ ] **Step 2: Split `push_tasks`**

In `src/clickup.py`, replace the whole `push_tasks` function with:

```python
def push_context() -> tuple[list[dict], dict[str, str], str | None]:
    """Members, alias map and backlog list — fetched once per batch of writes."""
    from .assignees import alias_map, get_members

    try:
        members = get_members()
    except Exception:
        members = []
    # A newly found defect belongs in the backlog, not in the running sprint. With no
    # backlog list configured everything still lands in the main list, tagged with
    # the intended destination, so nothing is silently lost.
    return members, alias_map(), os.environ.get("CLICKUP_BACKLOG_LIST_ID")


def push_one(
    task: dict,
    list_id: str,
    members: list[dict],
    aliases: dict[str, str],
    backlog_id: str | None,
) -> dict:
    """Create one task: resolve the owner, route to the backlog, tag type/destination.

    Returns {ok, info, assigned, backlog}. One task at a time so a caller can record
    exactly which effect succeeded — the idempotency key is committed per effect.
    """
    from .assignees import resolve_owner

    assignee_id = resolve_owner(task.get("owner"), members, aliases)
    wants_backlog = str(task.get("destination", "")).lower() == "backlog"
    target = backlog_id if (wants_backlog and backlog_id) else list_id

    task = dict(task)
    tags = [t for t in task.get("tags", []) if t]
    for marker in (task.get("type"), task.get("destination")):
        marker = str(marker or "").lower()
        if marker in ("bug", "backlog") and marker not in tags:
            tags.append(marker)
    task["tags"] = tags

    ok, info = _create_task(target, task, assignee_id)
    return {
        "ok": ok,
        "info": info,
        "assigned": bool(assignee_id) and ok,
        "backlog": wants_backlog and ok,
    }


def push_tasks(tasks: list, list_id: str | None = None) -> dict:
    """Create every task in the target list. Returns a summary dict."""
    list_id = list_id or os.environ.get("CLICKUP_LIST_ID")
    if not list_id:
        raise WorkbenchError(
            "No target list. Set CLICKUP_LIST_ID in your .env or pass a list_id."
        )
    if not tasks:
        raise WorkbenchError("There are no tasks to send. Generate artifacts first.")

    members, aliases, backlog_id = push_context()
    created, assigned, to_backlog, failures = 0, 0, 0, []
    for task in tasks:
        res = push_one(task, list_id, members, aliases, backlog_id)
        if res["ok"]:
            created += 1
            assigned += res["assigned"]
            to_backlog += res["backlog"]
        else:
            failures.append(res["info"])

    return {
        "created": created,
        "assigned": assigned,
        "backlog": to_backlog,
        "backlog_list_configured": bool(backlog_id),
        "failed": failures,
        "total": len(tasks),
        "list_url": list_url(list_id),
    }
```

Run: `python -m pytest -q`
Expected: `77 passed`.

- [ ] **Step 3: Write the failing tests for `apply_plan`**

Create `tests/test_apply.py`:

```python
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
```

Run: `python -m pytest tests/test_apply.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.apply'`.

- [ ] **Step 4: Write `src/apply.py`**

```python
"""Apply a board plan to the tracker — create what is new, comment on what exists — once.

The plan is a set of effects. Each one is keyed the way the n8n Idempotency check node
keys it and checked against the same store, so the app and the workflow share one
memory of what has already been applied. A key is committed only after its effect
succeeded; a failure leaves the effect free to be retried.
"""

from __future__ import annotations

import os
from datetime import date, datetime, timezone
from pathlib import Path

from .clickup import add_comment, list_url, push_context, push_one
from .client import WorkbenchError
from .idempotency import IdempotencyStore, effect_key
from .reconcile import GATE, split_by_confidence

STORE_PATH = Path(__file__).resolve().parent.parent / "state" / "processed_effects.jsonl"


def comment_body(item: dict) -> str:
    """What the comment is about — and the only thing its key is computed from."""
    return (item.get("detail") or item.get("description") or item.get("name") or "").strip()


def comment_text(item: dict, meeting_title: str, when: str) -> str:
    """The comment a matched task receives: where it came from, then what was said.

    `when` is the date of the MEETING, which the person running this supplies. It is not
    today's date, and it is not part of the key.
    """
    return f'From the meeting "{meeting_title}" ({when}):\n{comment_body(item)}'


def create_key(task: dict) -> str:
    return effect_key("NEW", "", f"{task.get('name', '')} {task.get('description', '')}".strip())


def comment_key(item: dict) -> str:
    """Keyed on the body, never on the rendered comment.

    The rendered text carries the meeting title and date, so hashing it would hand the
    same effect a fresh key on a different day and comment twice. It would also disagree
    with the n8n Idempotency check node, which hashes the item body alone — and two
    stores that compute different keys for one effect are not one store, which is the
    whole reason both write to this file.
    """
    return effect_key("UPDATE", item.get("target_id", ""), comment_body(item))


def as_effects(decisions: list, decided: list, threshold: float = GATE) -> tuple:
    """One (create, comment, ask) plan over both kinds of decision.

    A reconciled task carries `decision` NEW/UPDATE; a reconciled meeting decision carries
    `effect` comment/ask and structurally cannot be a create. Two shapes, the same three
    outcomes — so each item is stamped with `intent` and the caller stops caring which
    kind it was. Without this the plan tab showed decisions as comments and the button
    never sent them.
    """
    create, comment, ask = split_by_confidence(decisions, threshold)
    for d in create:
        d["intent"] = "create"
    for d in comment:
        d["intent"] = "comment"
    for d in ask:
        d["intent"] = "create" if d.get("decision") == "NEW" else (
            "comment" if d.get("target_id") else "")

    for d in decided:
        # A decision comments on work that exists, or goes to a human. Never a new task.
        d["intent"] = "comment" if d.get("target_id") else ""
        if d.get("effect") == "comment" and d.get("confidence", 0) >= threshold and d["intent"]:
            comment.append(d)
        else:
            ask.append(d)
    return create, comment, ask


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def apply_plan(
    create: list[dict],
    comment: list[dict],
    list_id: str | None = None,
    store: IdempotencyStore | None = None,
    meeting_title: str = "",
    when: str | None = None,
) -> dict:
    """Create every `create` item and comment on every `comment` item, each at most once."""
    list_id = list_id or os.environ.get("CLICKUP_LIST_ID")
    if not list_id:
        raise WorkbenchError("No target list. Set CLICKUP_LIST_ID in your .env or pick a list.")
    if not create and not comment:
        raise WorkbenchError("The plan has nothing to apply.")
    store = store or IdempotencyStore(STORE_PATH)
    # The caller passes the meeting's date. Today is only the fallback for a caller that
    # has none — and it never reaches the key, so the fallback cannot cause a second
    # comment tomorrow.
    when = when or date.today().isoformat()
    members, aliases, backlog_id = push_context()

    summary = {
        "created": 0, "commented": 0, "skipped": 0, "assigned": 0, "backlog": 0,
        "failed": [], "total": len(create) + len(comment), "list_url": list_url(list_id),
    }

    for task in create:
        key = create_key(task)
        if store.is_duplicate(key):
            summary["skipped"] += 1
            continue
        store.mark_seen(key)
        res = push_one(task, list_id, members, aliases, backlog_id)
        if res["ok"]:
            store.commit(key, {"kind": "NEW", "target": None,
                               "preview": task.get("name", "")[:60], "ts": _now(), "source": "app"})
            summary["created"] += 1
            summary["assigned"] += res["assigned"]
            summary["backlog"] += res["backlog"]
        else:
            summary["failed"].append(res["info"])

    for item in comment:
        text = comment_text(item, meeting_title, when)
        key = comment_key(item)
        if store.is_duplicate(key):
            summary["skipped"] += 1
            continue
        store.mark_seen(key)
        ok, info = add_comment(item["target_id"], text)
        if ok:
            store.commit(key, {"kind": "UPDATE", "target": item["target_id"],
                               "preview": item.get("name", "")[:60], "ts": _now(), "source": "app"})
            summary["commented"] += 1
        else:
            summary["failed"].append(info)

    return summary
```

Run: `python -m pytest -q`
Expected: `82 passed`.

- [ ] **Step 5: Replace the Send button with Apply plan**

In `app.py`, change the import `from src.clickup import get_lists, get_tasks, push_tasks` to `from src.clickup import get_lists, get_tasks` and add `from src.apply import apply_plan, as_effects`.

Replace the whole `render_clickup` function with:

```python
def render_apply(result: dict) -> None:
    """The plan, and one button that applies it — once, to the board it was built on."""
    if not os.environ.get("CLICKUP_API_TOKEN"):
        return  # integration not configured — hide the control entirely
    scope_id = result.get("scope_id")
    if not scope_id:
        st.caption("No ClickUp list was selected for this run, so the plan cannot be applied.")
        return
    # Both kinds of decision, one plan. A meeting decision that was only rendered in the
    # tab and never sent would make the tab a promise the button does not keep.
    create, comment, ask = as_effects(result["decisions"], result.get("decided", []))
    # The plan belongs to the board it was reconciled against. If the picker has moved
    # since, applying would write into a board this plan never saw.
    stale = st.session_state.get("scope_choice_id", scope_id) != scope_id

    with st.container(border=True):
        st.caption(
            f"Plan for **{result.get('scope_label', scope_id)}** · create **{len(create)}** · "
            f"comment on existing **{len(comment)}** · ask a human **{len(ask)}** "
            f"(gate {GATE:.2f})"
        )
        if stale:
            st.warning(
                "The list changed after this plan was built. Generate again before applying — "
                "writing a plan to a board it was not reconciled against is how duplicates "
                "are made."
            )
        # Items below the gate are applied only when a person ticks them, one by one,
        # the way the agent intended. This is the human in the loop, not auto-apply.
        approved = []
        for i, d in enumerate(ask):
            intent = d.get("intent", "")
            label = (f"{intent or 'no safe action'} · **{d.get('name', '')}** — "
                     f"{d.get('reason', '')} (confidence {d.get('confidence', 0):.2f})")
            if intent and st.checkbox(label, key=f"ask_{i}"):
                approved.append(d)
            elif not intent:
                st.caption(f"⚠️ {label} — needs manual handling")

        if st.button("📤 Apply plan to ClickUp", use_container_width=True, key="apply_plan",
                     disabled=stale):
            extra_create = [d for d in approved if d["intent"] == "create"]
            extra_comment = [d for d in approved if d["intent"] == "comment"]
            try:
                with st.spinner("Applying the plan…"):
                    summary = apply_plan(
                        create + extra_create, comment + extra_comment, scope_id,
                        meeting_title=result["context"].get("meeting_title", ""),
                        when=result.get("meeting_date"),
                    )
                st.success(
                    f"Created {summary['created']} · commented {summary['commented']} · "
                    f"skipped {summary['skipped']} already applied · "
                    f"{summary['assigned']} assigned to an owner."
                )
                st.markdown(f"➡️ [Open the ClickUp board]({summary['list_url']})")
                if summary["failed"]:
                    st.warning(
                        f"{len(summary['failed'])} effect(s) didn't go through: "
                        + "; ".join(summary["failed"][:3])
                    )
            except (WorkbenchError, ValueError) as exc:
                st.error(str(exc))
```

The list picker is gone from this control — it lives above **Generate** now (Task 3), and that
is where `_cached_lists()` is called. `app.py` never imports `split_by_confidence`:
`as_effects` wraps it, because the button has to route meeting decisions too.

and change the call `render_clickup(result["tasks"])` to `render_apply(result)`.

- [ ] **Step 6: Compile, test, and try it twice**

```bash
python -m py_compile app.py && python -m pytest -q
```
Expected: `82 passed`.

In the running app (preview `workbench-app`): Generate on the demo transcript, open the control, tick nothing, click **Apply plan to ClickUp**. Expected: `Created N · commented M · skipped 0`. Click again. Expected: `Created 0 · commented 0 · skipped N+M already applied`. Open the ClickUp list: one new task per `create` item, one comment per `comment` item, no duplicates. Check `state/processed_effects.jsonl` gained `N+M` lines with `"source": "app"`.

Three more checks the review asked for, none of which cost a model call:

```bash
# 1. A later meeting date must not produce a second comment.
python - <<'PY'
from pathlib import Path
from src.apply import comment_key, comment_text
item = {"name": "Saved cards update", "detail": "provider fixed the sandbox",
        "target_id": "86abc", "decision": "UPDATE"}
assert comment_key(item) == comment_key(item)
print("today :", comment_text(item, "Weekly sync", "2026-09-09").splitlines()[0])
print("later :", comment_text(item, "Weekly sync", "2026-09-12").splitlines()[0])
print("key   :", comment_key(item), "(same for both — the date is not hashed)")
PY
```

2. Change the list in the picker **after** a run: the control shows the stale-plan warning and the Apply button is disabled until Generate is pressed again.

3. Decisions reach the button: the Board plan tab's `## Decisions` section lists a comment on an existing task, and the caption above the button counts it in `comment on existing`. Applying it puts the comment on that task in ClickUp.

- [ ] **Step 7: Commit**

```bash
git add src/clickup.py src/apply.py app.py tests/test_clickup_write.py tests/test_apply.py
git commit -m "The app applies the plan, not the task list, and only once

Send to ClickUp pushed every generated task, blind to the board, and a second
click pushed them all again. The button now applies the plan: create what is
new, comment on what exists, and offer each item below the gate as its own
checkbox applied the way the agent intended. Every effect goes through the
idempotency store with the key spec the n8n node uses, so the two share one
memory and a second click applies nothing.

push_tasks is split into push_context and push_one so a key is committed only
after that one effect succeeded; a failure leaves the effect free to retry.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

## Task 5: The n8n sync workflow carries the shared prompt and the rich board

**Files:**
- Create: `scripts/__init__.py` (empty), `scripts/sync_n8n_match_prompt.py`
- Modify: `n8n/meeting-to-clickup-sync.workflow.json` (nodes `Match agent (Claude)`, `Board summary`, `Idempotency check`, `Mark processed`)
- Modify: `n8n/README.md`, `docs/n8n-case.html:109`
- Test: `tests/test_n8n_parity.py` (new)

**Interfaces:**
- Produces: `scripts.sync_n8n_match_prompt.render(prompt: str) -> str` (the n8n expression text), `NODE = "Match agent (Claude)"`, `patch(path: Path) -> None`.

- [ ] **Step 1: Write the failing parity tests**

Create `scripts/__init__.py` (empty) and `tests/test_n8n_parity.py`:

```python
"""The n8n export must carry what the Python path carries. Drift here is silent."""

import json
from pathlib import Path

from scripts.sync_n8n_match_prompt import NODE, render

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / "n8n" / "meeting-to-clickup-sync.workflow.json"


def _node(name: str) -> dict:
    data = json.loads(WORKFLOW.read_text(encoding="utf-8"))
    return next(n for n in data["nodes"] if n["name"] == name)


def test_render_swaps_format_fields_for_n8n_expressions():
    out = render("EXISTING TASKS:\n{board}\nName: {name}\nDetail: {detail}\n")
    assert out.startswith("=EXISTING TASKS:")
    assert "{{ $('Board summary').first().json.boardText }}" in out
    assert "{{ $json.name }}" in out and "{{ $json.description }}" in out
    assert "{board}" not in out and not out.endswith("\n")


def test_the_match_agent_carries_the_shared_prompt():
    # This is the drift WB-21 closed for the eval, found again in n8n on 2026-09-09.
    expected = render((ROOT / "prompts" / "match.md").read_text(encoding="utf-8"))
    assert _node(NODE)["parameters"]["messages"]["values"][0]["content"] == expected


def test_the_board_summary_shows_status_owner_and_due():
    code = _node("Board summary")["parameters"]["jsCode"]
    for marker in ("status:", "owner:", "due:"):
        assert marker in code


def test_state_and_log_both_live_under_wb_home():
    for name in ("Idempotency check", "Mark processed", "Log decision"):
        code = _node(name)["parameters"]["jsCode"]
        assert "$env.WB_HOME" in code, name
        assert "'state/processed_effects.jsonl'" not in code, name


def test_mark_processed_commits_one_effect_not_the_whole_batch():
    # It ran once for all items and committed every fresh key on the first successful
    # apply — so an item a human then rejected, or one still waiting in Telegram, was
    # recorded as applied. The app shares this store, so those effects vanished there too.
    node = _node("Mark processed")
    assert node["parameters"]["mode"] == "runOnceForEachItem"
    code = node["parameters"]["jsCode"]
    assert "$('Idempotency check').item" in code
    assert ".all()" not in code
```

Run: `python -m pytest tests/test_n8n_parity.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.sync_n8n_match_prompt'`.

- [ ] **Step 2: Write the sync script**

Create `scripts/sync_n8n_match_prompt.py`:

```python
#!/usr/bin/env python3
"""Write prompts/match.md into the n8n Match agent node, so the two cannot drift.

    python scripts/sync_n8n_match_prompt.py                       # the repo export
    python scripts/sync_n8n_match_prompt.py /tmp/sync-live.json    # an exported live copy

The node holds an n8n expression: the same text, with n8n placeholders where the
Python module has format fields. tests/test_n8n_parity.py fails when they differ.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT = ROOT / "n8n" / "meeting-to-clickup-sync.workflow.json"
NODE = "Match agent (Claude)"
PLACEHOLDERS = {
    "{board}": "{{ $('Board summary').first().json.boardText }}",
    "{name}": "{{ $json.name }}",
    "{detail}": "{{ $json.description }}",
}


def render(prompt: str) -> str:
    """prompts/match.md -> the text of the n8n node (an expression, hence the '=')."""
    out = prompt
    for field, expression in PLACEHOLDERS.items():
        out = out.replace(field, expression)
    return "=" + out.rstrip("\n")


def patch(path: Path) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    node = next(n for n in data["nodes"] if n["name"] == NODE)
    prompt = (ROOT / "prompts" / "match.md").read_text(encoding="utf-8")
    node["parameters"]["messages"]["values"][0]["content"] = render(prompt)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"patched '{NODE}' in {path}")


if __name__ == "__main__":
    patch(Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT)
```

- [ ] **Step 3: Patch the repo export — prompt, board summary, store path**

```bash
python scripts/sync_n8n_match_prompt.py
python - <<'PY'
import json
from pathlib import Path
p = Path("n8n/meeting-to-clickup-sync.workflow.json")
data = json.loads(p.read_text(encoding="utf-8"))
nodes = {n["name"]: n for n in data["nodes"]}

nodes["Board summary"]["parameters"]["jsCode"] = """// The board as the agent sees it — mirrors board_summary() in src/reconcile.py:
// id | name, then status / owner / due when the task carries them.
const lines = $input.all().map(i => {
  const t = i.json;
  const parts = [`${t.id} | ${t.name}`];
  const status = (t.status && t.status.status) || '';
  if (status) parts.push(`status: ${status}`);
  const owners = (t.assignees || []).map(a => a.username).filter(Boolean).join(', ');
  if (owners) parts.push(`owner: ${owners}`);
  if (t.due_date) parts.push(`due: ${new Date(Number(t.due_date)).toISOString().slice(0, 10)}`);
  return parts.join(' | ');
});
return [{ json: { boardText: lines.join('\\n'), count: lines.length } }];"""

home = ("const base = $env.WB_HOME;\n"
        "if (!base) throw new Error('Set WB_HOME to the checkout path of ai-product-ops-workbench (see n8n/README.md).');\n"
        "const STORE = base + '/state/processed_effects.jsonl';")
code = nodes["Idempotency check"]["parameters"]["jsCode"]
assert "const STORE = 'state/processed_effects.jsonl';" in code
nodes["Idempotency check"]["parameters"]["jsCode"] = code.replace(
    "const STORE = 'state/processed_effects.jsonl';", home)

# Mark processed is rewritten, not patched: it ran once for the whole batch and read
# every fresh item, so the first successful apply committed the keys of items a human
# had rejected and items still waiting in Telegram. Per item, paired item only.
nodes["Mark processed"]["parameters"]["mode"] = "runOnceForEachItem"
nodes["Mark processed"]["parameters"]["jsCode"] = """// Runs once per item, AFTER an apply node, and commits ONLY that item's key.
// Reading $('Idempotency check').all() here committed the whole fresh batch as soon as
// one effect succeeded -- including effects a human rejected and effects still waiting
// for approval. The Python app reads this same store, so those effects were skipped
// there too, and the guard silently swallowed real work.
""" + home + """
const fs = require('fs');
let source;
try {
  source = $('Idempotency check').item.json;   // the item THIS apply came from
} catch (e) {
  throw new Error('Mark processed could not resolve its paired item from Idempotency check: ' + e.message);
}
if (!source || !source.idem_key || source.is_duplicate) return { json: { marked: 0 } };
let existing = new Set();
try {
  for (const line of fs.readFileSync(STORE, 'utf8').split('\\n')) {
    const s = line.trim(); if (!s) continue;
    try { existing.add(JSON.parse(s).key); } catch (e) {}
  }
} catch (e) { /* no store yet */ }
if (existing.has(source.idem_key)) return { json: { marked: 0 } };
fs.appendFileSync(STORE, JSON.stringify({
  key: source.idem_key,
  kind: source.is_update ? 'UPDATE' : 'NEW',
  target: source.target_id || null,
  preview: (source.name || '').slice(0, 60),
  ts: new Date().toISOString(),
  source: 'sync'
}) + '\\n');
return { json: { marked: 1 } };"""

p.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print("patched Board summary, Idempotency check, Mark processed")
PY
git diff --stat n8n/
```
Expected: the script prints `patched 'Match agent (Claude)' …`, the snippet prints its line, and the diff touches only `n8n/meeting-to-clickup-sync.workflow.json`.

Note the `mode` change: a Code node running `runOnceForEachItem` returns one `{ json: … }`, not a list, which is why the body ends in a single return.

- [ ] **Step 4: Run the tests**

Run: `python -m pytest -q`
Expected: `86 passed`. If `test_the_match_agent_carries_the_shared_prompt` fails, run `git diff n8n/` and check the file was rewritten with `indent=2` and `ensure_ascii=False` (the existing style — the arrow in the workflow name must stay a raw `→`, not `→`).

- [ ] **Step 5: Update the live n8n instance**

n8n must be stopped for the import (close its terminal window). Then:

```bash
npx --yes n8n export:workflow --id=SyncMeetingCU001 --output=/tmp/sync-live.json
python scripts/sync_n8n_match_prompt.py /tmp/sync-live.json
```
Re-run the Python snippet from Step 3 with `p = Path("/tmp/sync-live.json")` (same edits, the live copy carries credentials the repo export does not), then:

```bash
npx --yes n8n import:workflow --input=/tmp/sync-live.json
rm /tmp/sync-live.json
```

Edit the local launcher `start-n8n.command` (git-ignored, this machine only) so n8n knows the checkout and may use `fs`/`crypto`: before the `npx --yes n8n` line add

```bash
export WB_HOME="$(cd "$(dirname "$0")" && pwd)"
export NODE_FUNCTION_ALLOW_BUILTIN=fs,crypto
```

Start n8n (double-click `start-n8n.command`), open the sync workflow, and check the Match agent node's text ends with the rule about work someone is already doing. Execute the workflow from the canvas with the Telegram gate bypassed the way earlier runs did (threshold −1 on the `Confident?` node, or an approval in Telegram if a tunnel is up). Expected: `Log decision` appends to `evals/decision_log.jsonl` under the checkout and `Mark processed` appends to `state/processed_effects.jsonl` there too — the same file the app writes.

**Then the mixed-batch check, which is the point of the rewrite.** Set the `Confident?`
threshold so that some items pass automatically and at least one goes to Telegram (the demo
run splits naturally around 0.8; if a tunnel is not up, set the threshold so one item is
confident and one is not, and simply leave the Telegram card unanswered):

```bash
wc -l state/processed_effects.jsonl        # before
```

Run the workflow, let the automatic items apply, and **reject** the Telegram card (or leave
it unanswered). Then:

```bash
wc -l state/processed_effects.jsonl        # after
tail -5 state/processed_effects.jsonl
```

Expected: the store grew by exactly the number of items that were **actually applied** — the
rejected or unanswered one is absent. Before this change it grew by the whole fresh batch.
If `Mark processed` instead throws `could not resolve its paired item`, n8n is not carrying
the pairing through the ClickUp/HTTP node: that is the loud failure the node was written to
produce. Fall back to removing `Mark processed` from the automatic branch entirely (the app
still owns the store), record it in the PR, and open a ticket — do not restore the batch-wide
commit.

- [ ] **Step 6: Say it in the docs**

In `n8n/README.md`, under `## WB_HOME`, replace the sentence `The other two workflows do not read \`WB_HOME\` — only the sync one logs.` with:

```markdown
The sync workflow reads `WB_HOME` in three nodes — `Log decision`,
`Idempotency check` and `Mark processed` — so the decision log and the idempotency
store both live in the checkout, in the same files the Python app writes. The other
two workflows do not read it.

## Keeping the prompt in sync

The `Match agent (Claude)` node carries `prompts/match.md`, rendered by
`scripts/sync_n8n_match_prompt.py`. Run it after editing the prompt, on the repo
export and on an exported copy of the live workflow; `tests/test_n8n_parity.py`
fails whenever the two differ.
```

In `docs/n8n-case.html` line 109, change `Fetch the current ClickUp tasks (id + name).` to `Fetch the current ClickUp tasks (id, name, status, owner, due date).`

- [ ] **Step 7: Commit**

```bash
git add scripts/ tests/test_n8n_parity.py n8n/meeting-to-clickup-sync.workflow.json n8n/README.md docs/n8n-case.html
git commit -m "The n8n sync workflow carries the shared prompt and the rich board

The Match agent node had fallen two rules behind prompts/match.md — the drift
WB-21 closed for the eval, back in the workflow. A script now renders the prompt
into the node and a parity test fails when they differ, the way the idempotency
vectors guard the key spec. Board summary shows status, owner and due date as the
Python path does. The idempotency store is read under WB_HOME like the decision
log, instead of relative to wherever n8n was launched.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

## Task 6: Refresh the public demo and say what changed

**Files:**
- Modify: `docs/index.html` (regenerated), `docs/report-preview.png` (optional), `README.md`

- [ ] **Step 1: Run the current pipeline on the demo transcript**

```bash
python workbench.py samples/transcript_demo.txt
grep -c "By Speaker" outputs/report.html
```
Expected: the run prints `Board: live ClickUp list (…)`, four stages, `Done. N tasks generated.`; the grep prints `2` (tab and pane). About ten model calls.

- [ ] **Step 2: Publish it**

```bash
cp outputs/report.html docs/index.html
grep -c "By Speaker" docs/index.html
```
Expected: `2`.

If Google Chrome is installed, refresh the hero image too:

```bash
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless=new --hide-scrollbars \
  --window-size=1400,880 --force-device-scale-factor=2 \
  --screenshot="$PWD/docs/report-preview.png" "file://$PWD/docs/index.html"
```
Expected: `docs/report-preview.png` rewritten at 2800×1760; open it and check the tabs row shows By Speaker. If Chrome is absent, skip this and say so in the PR.

- [ ] **Step 3: README — the plan tab and the apply button**

In `README.md`, replace the paragraph starting `**Send to ClickUp (optional):**` with:

```markdown
**Board plan and apply (optional):** with `CLICKUP_API_TOKEN` and `CLICKUP_LIST_ID` set,
the app reads the board before the first model call, and a fifth tab, **Board plan**,
shows what the run would do to it — create, comment on an existing task, or ask a
human — with the agent's reason for each. One button applies that plan: new tasks are
created titled, prioritized, tagged and **assigned to the resolved owner**; matched
points land as comments carrying the meeting title and date. Items below the confidence
gate are applied only if you tick them, one by one. Every effect goes through the same
idempotency store the n8n workflow uses, so clicking twice applies nothing twice. Owner
names resolve via an alias map (`OWNER_ALIASES`) → fuzzy match on workspace members →
unassigned fallback.
```

In `## Project layout`, add under `clickup.py`:

```
  apply.py          applies a plan to the board, each effect at most once
```

In `## The apply gate`, replace the first paragraph with:

```markdown
The pipeline builds a plan and stops. The CLI writes `outputs/board_plan.md` and never
touches the tracker; the web app shows the same plan and applies it only when a person
clicks, with anything below the gate opted in item by item. Nothing is written on the
pipeline's own judgement. That is a decision, not an unfinished feature — and the reason
is the shape of the misses, not the headline number.
```

- [ ] **Step 4: Run the tests and commit**

```bash
python -m pytest -q
git add docs/index.html docs/report-preview.png README.md
git commit -m "Refresh the public demo, and describe the plan tab

docs/index.html was generated on 15 July and predated the per-speaker view, the
type/destination markers and the board plan. It is now a fresh render of the
current pipeline. The README describes the Board plan tab and the apply button,
and the apply-gate section says where the human click sits.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```
(Drop `docs/report-preview.png` from the `git add` if it was not regenerated.)

- [ ] **Step 5: Open the PR**

```bash
git push -u origin HEAD
gh pr create --base main --title "M1: the app, the CLI and n8n tell one story" --body "$(cat <<'BODY'
Implements M1 of docs/superpowers/specs/2026-09-09-reusable-pipeline-program-design.md.

- The web app reads the board before the first model call, runs stage 2.5 over the generated tasks, and shows the board plan as a fifth tab.
- "Send to ClickUp" is now "Apply plan": create what is new, comment on what exists, opt in to items below the gate one by one. Every effect goes through the idempotency store with the n8n key spec; a second click applies nothing.
- get_tasks fails loudly on a bad token and reads every page. The CLI reads the board before stage 1.
- One confidence gate constant.
- The n8n sync workflow carries prompts/match.md (script + parity test), a board summary with status/owner/due, and WB_HOME-based state paths. Live instance updated.
- docs/index.html regenerated; README describes the plan tab.

No prompt file changed. No eval was run. Tests: 65 → 86.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
BODY
)"
```

---

## Self-review

- **Spec coverage.** M1 decisions → tasks: stage 2.5 + Board plan tab (Task 3); reconcile over tasks in both paths (Task 3); Apply plan with opt-in asks (Task 4); `src/apply.py` + store sharing the n8n key spec (Task 4); comment carries title and date (Task 4); `push_context`/`push_one` (Task 4); `get_tasks` loud failure + paging (Task 2); board read before stage 1 in CLI and app (Tasks 2, 3); `GATE` constant (Task 1); n8n script + parity test + board summary + `WB_HOME` + live update (Task 5); `docs/index.html` and README (Task 6). Definition of done items all have a step.
- **Placeholders.** None: every code step carries the code; the optional screenshot step names the command and the skip condition.
- **Type consistency.** `push_one` returns `{ok, info, assigned, backlog}` in Task 4's implementation, tests and `apply_plan`; `apply_plan`'s signature matches its tests and the app call; `render(prompt) -> str` and `NODE` match between script and parity test; `result["decisions"]`/`result["context"]` set in Task 3 and read in Task 4; `GATE` imported in Task 3's app imports and used in Task 4's caption.
- **Test count trail.** 65 → 66 (T1) → 72 (T2) → 74 (T3) → 78 (T4 push_one) → 89 (T4 apply, including the second-day, n8n-key and as_effects tests) → 94 (T5, including the per-item commit test). The exact totals matter less than that each task's step says what it expects; if a number is off by one, trust the run.
- **Review response (2026-09-10).** Findings 2, 3, 4 and the date half of 5 are fixed inside these tasks. The rest are in the spec: 1 is an owner decision (Two apply policies), the structural half of 5 is the idempotency boundary table, 6 belongs to M3, 7 to the board definition and M5, 8 to how n8n is described, 9 to M2, 10 to M4/M5.
