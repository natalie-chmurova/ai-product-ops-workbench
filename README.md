# AI Product Ops Workbench

Turn a messy meeting transcript into the artifacts a product team actually needs —
**ClickUp-ready tasks, a sprint summary, a bug triage table, and a per-speaker
breakdown** — in one command.

### **[▶ Live demo](https://natalie-chmurova.github.io/ai-product-ops-workbench/)** · [📄 Case study](CASE_STUDY.md) · [⚙️ n8n version](https://natalie-chmurova.github.io/ai-product-ops-workbench/n8n-case.html)

[![AI Product Ops Workbench: a raw meeting transcript on the left, AI-generated ClickUp-ready tasks, a sprint summary and a bug triage table on the right](docs/report-preview.png)](https://natalie-chmurova.github.io/ai-product-ops-workbench/)

Product teams lose hours turning call recordings and raw notes into structured work.
This tool does the boring part: it reads the transcript, figures out what was decided,
who owns what, and what's broken, then writes the documents for you.

```
transcript.txt  ─►  workbench.py ─►  ┌ tasks.json          (ClickUp-ready)
                                     ├ sprint_summary.md   (stakeholder update)
                                     ├ bug_triage.md       (QA triage table)
                                     ├ speaker_summary.md  (per-person: status, commitments, blockers)
                                     └ report.html         (input → output, one page)
```

## How it works

A small three-stage pipeline built on the [Claude API](https://console.anthropic.com):

1. **Understand** — read the raw transcript and extract a clean, structured summary
   (decisions, action items with owners, bugs, risks). One shared summary keeps every
   document consistent.
2. **Build** — turn that summary into the deliverables, each driven by its own
   prompt so the "product ops logic" is readable and easy to tune. The per-speaker
   view also reads the transcript directly, since who said what is the whole point
   of it — it answers "where is each person, who is stuck", which a thematic
   summary flattens away.
3. **Present** — render a single self-contained `report.html` showing the raw meeting
   on the left and the generated artifacts on the right. No server, just open it.

Prompts live in [`prompts/`](prompts/) as plain Markdown — the product logic is
first-class and editable without touching code.

**Send to ClickUp (optional):** with a `CLICKUP_API_TOKEN` set, the web app shows a
"Send to ClickUp" button that creates the generated tasks — titled, prioritized, tagged,
and **assigned to the resolved owner** — directly in a ClickUp list, so a meeting turns
into a populated board in one click. Owner names resolve to real assignees via an alias
map (`OWNER_ALIASES`) → fuzzy match on workspace members → unassigned fallback.

## Run it

**Web app (point-and-click):**

```bash
pip install -r requirements.txt
cp .env.example .env          # then paste your Anthropic API key into .env
streamlit run app.py          # opens a browser: paste a transcript, click Generate
```

On macOS you can also just double-click `start.command` — it sets up the
environment on first run and launches the app.

**Command line (batch / scripting):**

```bash
python workbench.py samples/transcript_demo.txt   # a transcript...
python workbench.py samples/meeting_demo.m4a       # ...or an audio recording
open outputs/report.html      # macOS ("xdg-open" on Linux)
```

Pass an audio/video file and it is transcribed locally first (mlx-whisper — nothing
leaves the machine, no per-minute API cost), then run through the same pipeline.
A full run over the demo transcript costs a few cents.

## Project layout

```
workbench.py        CLI entry point / orchestrator
src/
  client.py         talks to the Claude API (prompt loading, JSON parsing, retries)
  extract.py        stage 1 — transcript → structured summary
  artifacts.py      stage 2 — summary → tasks / sprint / bug triage / per-speaker
  render.py         stage 3 — artifacts → report.html
  reconcile.py      stage 1.5 — check each point against the board before acting
  clickup.py        reads the board and writes to it
prompts/            the instructions for each stage (Markdown)
samples/            synthetic demo transcripts (no real/sensitive data)
evals/              the three eval harnesses, their labels and their results
outputs/            generated artifacts (git-ignored)
```

## Measuring it

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

## Notes

- The demo transcript is **synthetic** — a fictional team and product, safe to share.
- Task descriptions follow a real ClickUp ticket structure
  (Goal / Context / What needs to be done / Acceptance criteria).
- Built as a portfolio project demonstrating AI-assisted product operations.
