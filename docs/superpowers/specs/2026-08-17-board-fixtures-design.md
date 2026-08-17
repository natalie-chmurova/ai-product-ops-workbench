# Board fixtures and the effect eval — Design

**Date:** 2026-08-17
**Status:** Draft — awaiting review
**Scope:** WB-19, and the measurement WB-9 / WB-17 / WB-18 depend on

## Problem

The pipeline reads the board (WB-11) and produces `outputs/board_plan.md` — create /
comment on existing / ask a human / decisions. That plan cannot currently be judged,
because **the board the plan is reconciled against has nothing to do with the
transcript being processed**.

The live ClickUp demo list holds 11 tasks, all from the world of
`samples/transcript_demo.txt`: checkout, saved cards, product detail, image carousel.
Two of the three eval transcripts describe a different team-week entirely —
`transcript_messy_1` is about search ranking, a release date, tokenization, duplicated
push notifications; `transcript_messy_2` is about a tokenizer bug, a CDN incident,
price clipping. There is **not one overlapping task**.

Three consequences, all observed in live runs on 2026-08-17:

- **"Comment on existing: 0" is structurally forced** on both messy transcripts. There
  is nothing on the board those meetings could possibly be about. The half of the SOP
  that WB-11 exists to serve is not exercised at all.
- **The manager's `manager_notes` are unverifiable.** The validated ground truth says
  the Wednesday-release decision should become *a comment on the existing release
  task*, and that Sam's regression work should *have its deadline checked on the
  board*. Neither task exists on the board, so neither expectation can be checked.
- **Board clutter costs autonomy, invisibly.** On the demo transcript — the one whose
  world the board does match — the plan came out `create 1 · comment 3 · ask 5`. The
  three comments were all correct. But five items went to a human, and the agent's own
  reasons name the cause: the board carries three near-duplicate empty-images crash
  tasks and two near-duplicate saved-cards tasks, left over from old test runs. The
  agent wrote, unprompted, *"matching the existing dev task for that crash (though
  duplicate tasks exist)"*.

A separate defect surfaced while reading the code: `evals/eval_decisions.py` carries
its **own copy** of the match prompt (its `MATCH_PROMPT` constant) and has drifted
from `prompts/match.md` by two rules — "a decision the team reached is an UPDATE to
the work it concerns" and "work someone is already doing is an UPDATE, not a second
copy". WB-11 declared `prompts/match.md` the single source and `src/reconcile.py` says
so in its docstring, but the eval never read it. **The published 100/100 decision
numbers therefore measure an agent that lacks exactly the two rules we later added.**

## Goal / non-goals

**Goal.** Make the board plan judgeable: for every transcript, reconcile against a
board that represents the team's state *before* that meeting, and score the effect the
pipeline chooses for each point against the manager's labels.

**Non-goals.**

- **Implementing** `verify_deadline` / `verify_status`. This work delivers the
  *metric* for them, deliberately red on the first run. The mechanisms are WB-9 and
  WB-18 and stay separate, so their effect is visible as a before/after.
- Cleaning the live ClickUp board. The clutter is now a finding worth keeping: the
  fixture-vs-live comparison on the same input is the evidence for "board clutter
  costs autonomy".
- Touching the n8n workflows. Python path only.
- Auto-applying anything to the board. The pipeline still stops at the plan.

## Key decisions

### A fixture is a board, not a new concept

The format is not invented — it is whatever `get_tasks()` already returns, plus the
one field it does not yet read:

```json
{
  "transcript": "samples/transcript_messy_1.txt",
  "status": "DRAFT — awaiting Natallia's validation",
  "note": "The board as it stood BEFORE this meeting.",
  "tasks": [
    { "id": "B1",
      "name": "[Release] Cut the August release",
      "status": "in progress",
      "assignees": ["Dana"],
      "due_date": "2026-08-19" }
  ]
}
```

`get_tasks()` gains `due_date` (ClickUp returns epoch milliseconds; stored as an ISO
date, or `""` when unset) so a fixture board and a live board are the same shape. Any
code downstream can then be written once.

`assignees` stays a list, because that is what ClickUp returns and what
`get_tasks()` already produces. The `owner` the agent sees is that list joined with
`", "`; when it is empty the field is omitted from the line entirely rather than
rendered as `owner: none`. Stated here because it is otherwise the kind of detail that
gets decided twice, differently, in two files.

### The live board stays the default

The fixture is opt-in:

```
python workbench.py samples/transcript_messy_1.txt --board evals/board_messy_1.json
```

Without the flag the pipeline reads live ClickUp exactly as it does today. This is a
requirement, not a preference: the demo's value is that it writes to a real board, and
a fixture that quietly replaced it would hollow that out.

### The agent sees the fields, not just the names

`board_summary()` currently renders `id | name`, so `status` and `assignees` are read
from ClickUp and then thrown away before the agent ever sees them. It becomes
`id | name | status | owner | due`, omitting empty fields so the line stays readable.

Without this, WB-18 ("they said it's done — check the board") and WB-9 (deadline
changes) have nothing to reason over: the agent cannot check a status it was never
shown.

**This changes agent behaviour**, so decision numbers taken after it are not
comparable with numbers taken before. Both eval harnesses get re-measured, and the
change is stated wherever the old numbers are published.

### The effect eval feeds reconcile pre-extracted points

`evals/eval_effects.py` does **not** run extraction. It takes the points straight from
the validated ground truth and asks only: given this board, what effect does the
pipeline choose?

Mixing extraction in would fold two different failures into one number — a point the
extractor never found and a point the reconciler mis-routed would both read as "wrong",
and the fix for each is in a different place. `eval_decisions.py` already established
this separation; the new harness follows it.

Input is both sections of each ground truth file: `tasks` *and* `manager_notes`. The
manager notes are where the interesting expectations live, and they have been sitting
unscored since they were written.

### Five effects, two of them knowingly unimplemented

Ground truth files gain an explicit `expected_effect` from a closed vocabulary:

| Effect | Meaning | Implemented today |
|---|---|---|
| `create` | new task on the board | yes |
| `comment` | comment on an existing task | yes |
| `ask` | escalate to a human | yes |
| `verify_deadline` | check the date on the board, comment if it differs — never overwrite | **no** (WB-9) |
| `verify_status` | check the status, propose In Review, comment on the caveat | **no** (WB-18) |

Scoring is exact match, plus a separate target accuracy for `comment` (was it the
right task?). The first run will score **0% on `verify_deadline` and `verify_status`** —
that is the point. A metric that is red before the fix and green after is what makes
WB-9 and WB-18 provable rather than assertable.

### `ask` is only correct when the agent escalated for the right reason

`ask` is not a decision the agent makes — it is what happens when confidence falls
below the gate, whatever the cause. Scored naively, it becomes the effect that flatters
the metric: an item whose expected effect is `ask` would count as correct even when the
agent escalated because its answer could not be parsed, or because it matched a task id
that is not on the board. Both have been seen live — that is what the empty
`"confidence 0.00 —"` reason was.

So escalations are scored by cause, not just by outcome. `parse_decision` already
distinguishes the cases in prose; it gains a machine-readable `escalation_cause`:

| Cause | Meaning | Counts as a correct `ask` |
|---|---|---|
| `low_confidence` | the agent reached a decision and honestly doubted it | yes |
| `unreadable` | the reply could not be parsed | **no** |
| `phantom_target` | UPDATE naming a task id absent from the board | **no** |

The last two are the guardrails firing — the mechanism failing safe. Counting them as
a correct escalation would report a broken run as a good one.

Additionally, for an item whose expected effect is `ask`, the report records what the
agent was *about* to do (its underlying `decision` and `target_id`). An item that
escalated while pointing at the wrong task is a different animal from one that
escalated while pointing at the right one, and only the report can tell them apart.
`evals/effect_results.md` therefore breaks escalations down by cause and lists the
underlying intent for each, rather than collapsing them into one count.

### Drafted by the assistant, validated by the manager

The fixtures are drafted from the transcripts — a task goes on the pre-meeting board
when the transcript treats it as already existing ("we said we'd cut it Wednesday",
"I'm on regression until Wednesday"). Every file ships marked `DRAFT` and is not used
for any published number until Natallia has read it.

This is the same cycle the task ground truth went through, and for the same reason: if
the assistant both invents the right answer and grades against it, the grade means
nothing.

## Architecture

**`src/clickup.py`**
- `get_tasks()` also returns `due_date`.
- `load_board_fixture(path) -> list[dict]` — reads a fixture file and returns the same
  shape `get_tasks()` returns. A missing file or malformed JSON raises `WorkbenchError`
  with the path in the message; this is a developer-supplied argument, so failing loudly
  beats silently reconciling against an empty board.

**`src/reconcile.py`**
- `board_summary()` renders the richer line.
- `parse_decision()` returns `escalation_cause` — `""` | `low_confidence` |
  `unreadable` | `phantom_target`. The distinction already exists in the prose reasons
  written for the human; this makes it available to the scorer as well.

**`workbench.py`**
- `--board <path>` selects the fixture; absent, `get_tasks()` runs as today.

**`evals/eval_effects.py`** (new)
- Pairs each `ground_truth*.json` with its fixture through a new `"board"` field in the
  ground truth itself (`"board": "evals/board_demo.json"`). An explicit reference rather
  than a filename convention — the clean transcript's ground truth is `ground_truth.json`
  with no suffix, so a convention would have to name its fixture `board.json`, which says
  nothing. A ground truth with no `"board"` field is skipped, with a line in the report
  saying so.
- Feeds each point through `reconcile` / `reconcile_decisions` against that board.
- Scores effect accuracy overall and per effect, plus target accuracy for `comment`.
- Writes `evals/effect_results.md`, per transcript, in the style of `results.md`.
- `--dry-run` and `--only` flags, matching `run_eval.py`.

**`evals/eval_decisions.py`** — re-measured here, but **not modified here**. The richer
`board_summary` moves its numbers on its own; closing the prompt drift would move them
a second time, and a single re-measurement could not say which change did what. The
drift fix is WB-21, measured separately. One change per measurement.

**New data:** `evals/board_demo.json`, `evals/board_messy_1.json`,
`evals/board_messy_2.json`.

## Testing / proof

**pytest (no API):**
- `load_board_fixture` — well-formed file, missing file, malformed JSON.
- `get_tasks` maps `due_date` from epoch ms, and tolerates it being absent.
- `board_summary` renders the new fields and omits empty ones.
- Effect scoring — exact match, per-effect breakdown, target accuracy — against
  hand-built decision dicts.
- `escalation_cause` — an unparseable reply yields `unreadable`, an UPDATE naming an
  absent id yields `phantom_target`, an honest low score yields `low_confidence` — and
  the scorer credits a correct `ask` only for the last.

**Live runs (required, not optional):** every fixture is run through
`workbench.py --board …` and the resulting `board_plan.md` is read. WB-11 shipped a bug
that the unit tests missed precisely because they were fed idealised dicts — `reconcile`
returned `what` while the plan read `name`, so every heading rendered blank. A unit test
on invented data does not replace a run on real data.

**The measurement that justifies the work:**
- `demo` against its clean fixture vs. against the cluttered board — same transcript,
  same prompt, one variable. The difference in how many items escalate is the cost of
  board clutter, measured rather than asserted.

  The cluttered side is **a snapshot, not the live board**:
  `evals/board_demo_live_snapshot.json`, captured from ClickUp at measurement time and
  carrying the capture date. The live board is not a stable comparison surface — it has
  11 tasks today because of accumulated test runs, and it will have a different set
  after any cleanup. Comparing a fixture against a moving board yields a number nobody
  can reproduce next month; comparing two committed files yields one anybody can. The
  snapshot is committed precisely *because* it contains the duplicates — they are the
  independent variable, not noise to be tidied away.
- `messy_1` / `messy_2` against their fixtures — `comment` and the two `verify_*`
  effects become numbers for the first time.
- `eval_decisions` re-measured because `board_summary` changed under it — its code
  untouched, so the delta is attributable to that one change.

## Honest boundaries

- A fixture is a **model** of a board, not a board. It cannot surface what live ClickUp
  surfaces — duplicates, stale statuses, tasks nobody mentioned. Both paths are kept for
  that reason, and the live path stays the default.
- The two `verify_*` effects score 0% by construction here. Reporting them as a
  shortcoming of the pipeline is accurate; reporting them as a failed experiment is not.
- Numbers taken after the `board_summary` change are not comparable with numbers taken
  before it. Both harnesses are re-run, and the discontinuity is stated wherever the
  old numbers appear — as was done when the ground truth was re-labelled.

## Files touched

**New:**
- `evals/eval_effects.py`
- `evals/board_demo.json`, `evals/board_messy_1.json`, `evals/board_messy_2.json`
- `evals/board_demo_live_snapshot.json` — the cluttered board as captured, with its date
- `evals/effect_results.md` (generated)
- `tests/test_board_fixtures.py`

**Changed:**
- `src/clickup.py` — `due_date`, `load_board_fixture`
- `src/reconcile.py` — richer `board_summary`, `escalation_cause`
- `workbench.py` — `--board`
- `evals/ground_truth*.json` — a `"board"` reference, and `expected_effect` on tasks
  and manager notes
- `evals/results.md`, `evals/decision_results.md` — re-measured numbers

## Out of scope, noted for later

- Closing the `eval_decisions.py` prompt drift (WB-21) — a real defect with a real
  consequence for published numbers, but held separate so each re-measurement isolates
  one change.
- Implementing `verify_deadline` (WB-9) and `verify_status` (WB-18).
- Dependency links between tasks (WB-17) — the fixture format can carry them when that
  work starts; nothing here blocks it.
- Owner accuracy (WB-14) — a different axis, measured against `owner_hint`.
- Cleaning the live demo board.
