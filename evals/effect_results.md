# Effect eval (what the pipeline decides to DO) — 2026-08-18

Points come from the validated ground truth, not from extraction: an extraction miss and a routing miss are different defects and are kept as different numbers.

`verify_deadline` and `verify_status` have no implementation yet (WB-9, WB-18). They are measured anyway, and score zero, so the fix has something to move.

An `ask` counts as correct only when it came from honest doubt. An escalation caused by an unreadable reply or a target absent from the board is a guardrail firing, and crediting it would report a broken run as a good one.

**The effect labels were validated by Natallia on 18 Aug 2026.** Rows marked ⚑ are ones the fixtures forced a judgement on; each carries her verdict as a `review_note` in the ground truth.

## Summary

| transcript | board | points | effect accuracy | target accuracy |
|---|---|---|---|---|
| clean | `evals/board_demo.json` | 11 | 64% | 86% |
| messy 1 — reversed decision, ownerless item | `evals/board_messy_1.json` | 6 | 67% | 100% |
| messy 2 — noise, a task raised in passing, a hedged follow-up | `evals/board_messy_2.json` | 8 | 50% | 100% |

## clean

| expected effect | points | correct |
|---|---|---|
| `create` | 4 | 2 |
| `comment` | 7 | 5 |

Escalations by cause: `low_confidence` 4

| point | expected | got | cause | agent's intent |
|---|---|---|---|---|
| gt6 ⚑ | `create` | `ask` | low_confidence | UPDATE 86ey9z6rc |
| gt7 ⚑ | `comment` | `ask` | low_confidence | NEW NONE |
| gt8 | `create` | `ask` | low_confidence | NEW NONE |
| gt11 | `comment` | `ask` | low_confidence | UPDATE 86ey9z6qa |

## messy 1 — reversed decision, ownerless item

| expected effect | points | correct |
|---|---|---|
| `create` | 2 | 1 |
| `comment` | 3 | 3 |
| `verify_deadline` _(not implemented)_ | 1 | 0 |

Escalations by cause: `low_confidence` 1

| point | expected | got | cause | agent's intent |
|---|---|---|---|---|
| gt3 | `create` | `ask` | low_confidence | NEW NONE |
| Finish regression testing on the payment | `verify_deadline` | `comment` | — | UPDATE B2 |

## messy 2 — noise, a task raised in passing, a hedged follow-up

| expected effect | points | correct |
|---|---|---|
| `create` | 4 | 2 |
| `comment` | 2 | 2 |
| `verify_deadline` _(not implemented)_ | 1 | 0 |
| `verify_status` _(not implemented)_ | 1 | 0 |

Escalations by cause: `low_confidence` 2

| point | expected | got | cause | agent's intent |
|---|---|---|---|---|
| gt1 ⚑ | `create` | `ask` | low_confidence | NEW NONE |
| gt3 | `create` | `ask` | low_confidence | UPDATE B2 |
| Marco's search diagnosis slipped from Th | `verify_deadline` | `comment` | — | UPDATE B1 |
| Sam: 'regression is done, everything gre | `verify_status` | `comment` | — | UPDATE B2 |

## Board clutter, measured

Same transcript, same points, same prompt, same labels. Only the board differs.

| board | tasks | effect accuracy | escalations |
|---|---|---|---|
| `board_demo.json` (clean) | 8 | **64%** (7/11) | 4, all honest doubt |
| `board_demo_live_snapshot.json` (as it really is) | 11 | **55%** (6/11) | 5, one of them `unreadable` |

The snapshot is the same board with three duplicates earlier test runs left behind:
`86eyd348y` duplicating `86eyay0p7`, and `86eyd347m` and `86eyay0kt` both duplicating
`86ey9z6rc`. Nothing else differs — the clean fixture is the snapshot minus those three
rows, byte-identical otherwise.

**The mechanism is visible, not just the number.** On the clean board `gt1` produces a
correct comment. On the cluttered one the agent aims at `86eyd348y` — the *copy* rather
than the original — and loses enough confidence to escalate. `gt6` does the same, aiming
at `86eyay0kt`, the third copy of the crash fix. And `gt7` came back unparseable, so the
guardrail fired; scored by outcome alone that would have counted as a correct escalation,
which is exactly what the cause-based scoring exists to prevent.

Nine points of accuracy, one correct action turned into a question for a human, and one
unreadable reply — that is what three stale duplicates cost.

## What the misses actually are

Ten misses across the three transcripts, and they are not ten of the same thing.

**Three are the missing mechanism, and they fail in the most encouraging way possible.**
Every `verify_deadline` and `verify_status` point came back as `comment` **on the right
task** — B2, B1, B2. The agent finds the work correctly and then has no way to say
"check the date" or "check the status", so it does the only thing it can. WB-9 and WB-18
therefore need a new effect, not better matching: the matching half already works.

**Four are calibration, not judgement.** In `messy_1 gt3`, `clean gt8` and `messy_2 gt1`
the agent decided NEW — which is what the labels expect — and escalated only because it
scored below the 0.8 gate. In `clean gt11` it decided UPDATE and named
`86ey9z6qa`, the exact task the labels expect, and still escalated. The agent was right
and unsure at the same time, and this metric charges it as wrong.

That is a real limitation of the number as it stands: **effect accuracy folds judgement
and confidence calibration into one figure.** Counting the agent's underlying intent
instead, the same runs read 9/11, 5/6 and 5/8 — 82%, 83%, 63%. Neither number is the
honest one on its own; the pair is.

**Three are genuine mistakes.** `clean gt6` matched the regression cases to the crash fix
that produces them; `clean gt7` proposed a new budget task although the board already
carries the approval; `messy_2 gt3` matched the flaky checkout test to the payments
regression task. Those are the ones worth fixing in the prompt.

## What was deliberately not re-measured

The richer `board_summary` changes what the agent sees, so both other harnesses were
candidates for a re-run. Reading the code answered it more cheaply than an API call
could have:

- **`eval_decisions.py` never calls `board_summary`.** It builds its own board string
  (`BOARD_TEXT`, line 44). So this change cannot have moved its numbers, and its 100% /
  100% from earlier today still stands. Note this is the same defect that WB-21 just
  fixed one level up: the harness duplicating production logic instead of calling it.
  The prompt copy had drifted; this copy has not yet.
- **Extraction never sees the board.** `extract_context` takes a transcript and a
  roster, nothing else, so `run_eval`'s numbers cannot have moved either.

Roughly 39 model calls the plan would have spent, answered by reading instead.
