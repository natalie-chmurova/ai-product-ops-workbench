# Case Study — AI Product Ops Workbench

**One-liner:** I built a tool that turns a raw product-meeting transcript into
ClickUp-ready tasks, a stakeholder sprint summary, and a bug triage table — in one
command, in seconds.

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

What would take a person a careful hour took the tool a few seconds and a few cents.

## Business value

- **Meeting-to-task time: from ~an hour to under a minute.** The tedious part of product
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

## Links

- **Live report (visual):** _(GitHub Pages — enabled when the repo goes public)_
- **Code:** github.com/natalie-chmurova/ai-product-ops-workbench
- **Demo video:** _(Loom — to be recorded)_

> Built as a portfolio project. All demo data is synthetic — a fictional team and product.
