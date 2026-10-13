# Case Study — AI Product Ops Workbench

**One-liner:** I built a tool that turns a raw product-meeting transcript into
ClickUp-ready tasks, a stakeholder sprint summary, and a bug triage table — in one
command, in under two minutes.

---

## The problem

Every product team drowns in the same busywork. A 35-minute sync produces decisions,
action items, owners, bugs, and risks — but all of it is buried in a messy transcript.
Someone (usually the PM or product ops person) then spends an hour or more turning that
noise into structured work: writing tickets, summarizing for stakeholders, triaging bugs.

It's high-effort, low-leverage work, and it's exactly the kind of thing that gets done
late, inconsistently, or not at all — so decisions get lost and bugs slip through.

## What I built

A small, focused tool — the **AI Product Ops Workbench** — that automates the
meeting-to-artifacts step. You give it a transcript; it gives you back the documents a
product team actually needs, ready to use.

**Input:** one meeting transcript.
**Output:**
- **ClickUp-ready tasks** — titled, owned, prioritized, with a description in the team's
  real ticket structure (Goal / Context / What to do / Acceptance criteria).
- **Sprint summary** — a scannable stakeholder update: highlights, decisions, in-progress,
  next up, risks & blockers.
- **Bug triage table** — each bug with severity, priority, and a suggested next action.
- **A single HTML report** showing the raw meeting on the left and everything the tool
  generated on the right.

## How it works

A three-stage pipeline built on the Claude API:

1. **Understand** — read the messy transcript and extract a clean, structured summary
   (decisions, action items with owners, bugs, risks). This shared understanding keeps
   every downstream document consistent with the others.
2. **Build** — turn that summary into the three deliverables, each driven by its own
   editable prompt so the "product ops logic" is transparent and tunable.
3. **Present** — render a self-contained report page. No server, no setup — just open it.

The design choice I'm most deliberate about: everything is generated from **one shared
understanding** of the meeting, not three independent passes. That's cheaper, faster, and
means the tasks, the summary, and the triage never contradict each other.

## The output, concretely

On a synthetic 35-minute product sync for a fictional marketplace app, one run produced:

- **9 structured, prioritized tasks** — correctly assigning a user-facing crash as
  *Urgent*, a low-severity search bug as *Low*, and routing owners accurately (it even
  captured an engineer named mid-meeting who wasn't on the attendee list).
- **A full sprint summary** — decisions, what's shipping, what's next, and the real risks
  (a blocking vendor dependency and thin Android test coverage).
- **A bug triage table** with severities, P0–P3 priorities, and concrete next actions.

What would take a person a careful hour takes the tool under two minutes and a few cents
(measured on 13 October 2026: 104 seconds for the full run on this transcript — all four
documents and the report — with each document written by its own model call).

## Business value

- **Meeting-to-task time: from ~an hour to under two minutes.** The tedious part of product
  ops becomes instant, so it actually gets done — every time, consistently.
- **Nothing falls through the cracks.** Decisions, owners, and bugs are captured
  structurally instead of living in someone's memory or a forgotten notes doc.
- **Stakeholders get a clean update for free**, generated from the same source of truth as
  the tasks — no separate write-up step.
- **Reusable across product, dev, design, and QA.** The same input serves all four.

## What this demonstrates

- Practical **AI automation of a real operational workflow** — not a toy demo.
- **Prompt engineering as product logic:** the behavior lives in readable, editable prompt
  files, treated as first-class.
- **Judgment about scope:** a focused, polished tool that solves one real problem well,
  rather than an over-built SaaS.

## Measuring it

Since this case study was first written, the tool learned to read the ClickUp board
before it writes: every point becomes a new task, a comment on a task that already
exists, or a question for a person, and that plan is applied only when someone clicks.
Deciding *what to do to the board* is the hard part, so it is what is measured most.

Three harnesses, each answering a different question. All of them run against labels a
delivery manager validated by hand, and all of them are allowed to fail.

| harness | question | latest |
|---|---|---|
| `evals/run_eval.py` | was the work found? | recall 100%, precision 100% on three transcripts |
| `evals/eval_decisions.py` | new work or an update to something that exists? | 100% decision, 100% target |
| `evals/eval_effects.py` | what should actually happen to the board? | 64% / 67% / 50% |

The third is new and deliberately red. Two of the five effects it scores —
`verify_deadline` and `verify_status` — have no implementation at all, so they report
zero on purpose: the metric exists before the feature, so the feature has something to
move.

It also measures what a messy board costs. On the same transcript with the same labels,
a board carrying three duplicate tasks left by old test runs scores **55%** against
**64%** for the same board with the duplicates removed — and the failure is legible:
the agent matches the copy instead of the original and escalates rather than acting.

Two honest caveats, both written into the results files rather than left to be
discovered: effect accuracy folds judgement together with confidence calibration (in
four of ten misses the agent decided exactly what the labels expect and escalated anyway,
below the gate), and the decision eval's ten points do not reach two of the rules its own
prompt now carries.

One full run of the effect eval saves the agent's raw matches to
`evals/effect_decisions.json`. The file is not in the repository — producing it takes one
run with an API key — but once it exists, asking where the gate belongs is a re-read
rather than another run: the model call is the expensive half of that harness and the
confidence gate is the cheap one.

```bash
python evals/eval_effects.py                      # one full run: calls the model, saves the raw matches
python evals/eval_effects.py --sweep              # then: accuracy across gates 0.50-0.95, no API calls
python evals/eval_effects.py --replay --threshold 0.7
```

That matters because calibration is the largest bucket of misses — four of ten — so the
cheapest available experiment is also the one aimed at the biggest share of the failure.
The sweep is still scored against the labels it would be tuned on, so it reports what a
threshold could have bought on this set, not what to set it to.


## The apply gate

The pipeline builds a plan and stops. The CLI writes `outputs/board_plan.md` and never
touches the tracker; the web app shows the same plan and applies it only when a person
clicks, with anything below the gate opted in item by item. Nothing is written on the
pipeline's own judgement. That is a decision, not an unfinished feature — and the reason
is the shape of the misses, not the headline number.

### What the 50–67% is actually made of

Ten misses across the three transcripts, and they are three different things:

| bucket | misses | what happened |
|---|---|---|
| calibration | 4 | the agent chose exactly what the labels expect, scored below the 0.8 gate, and escalated anyway |
| no mechanism | 3 | a `verify_deadline` / `verify_status` point with nothing to express it — each landed as a comment on the **right** task (B2, B1, B2) |
| judgement | 3 | the agent genuinely matched the wrong thing |

So **three of ten are real errors of judgement.** Counting the agent's underlying intent
rather than the gated outcome, the same runs read **82% / 83% / 63%**.

Neither number is the honest one alone. Effect accuracy folds judgement together with
confidence calibration, and quoting only the low figure understates the agent as badly as
quoting only the high one would flatter it. The pair is the measurement.

### Why the gate stays closed anyway

- **Three judgement errors in ten is still too many to write into a live board.** The
  calibration misses are safe failures — they escalate to a human. The judgement ones are
  not: they act confidently on the wrong task.
- **Two of the five effects do not exist.** `verify_deadline` and `verify_status` (WB-9,
  WB-18) have no implementation, so a point needing one degrades to a comment. Applying
  now would silently convert "check this date" into "leave a note".
- **On a cluttered board the agent aims at the duplicate.** Not hypothetical: the live
  board carried three duplicate rows from old test runs, and the agent matched the copy
  instead of the original. Idempotency stops the same effect being applied twice; it does
  not stop the correct effect landing on the wrong task.

And the number is probably generous. These transcripts are the ones the extraction and
routing rules were derived from — there is no held-out set. On a meeting the rules have
never seen, expect lower, not higher. Until a held-out transcript exists, 50–67% is a
ceiling estimate rather than a floor.

The gate reopens when WB-9 and WB-18 land and the effect eval is re-run against a
transcript that did not shape the rules.

## Links

- **Live demo:** [natalie-chmurova.github.io/ai-product-ops-workbench](https://natalie-chmurova.github.io/ai-product-ops-workbench/)
- **n8n version:** [the agentic workflow, step by step](https://natalie-chmurova.github.io/ai-product-ops-workbench/n8n-case.html)
- **Code:** [github.com/natalie-chmurova/ai-product-ops-workbench](https://github.com/natalie-chmurova/ai-product-ops-workbench)

> Built as a portfolio project. All demo data is synthetic — a fictional team and product.
