# Deepening the effect, the plan and the store — Design

**Date:** 2026-09-12
**Status:** Draft — decided by the assistant while the owner was away; awaiting the owner's review. Stacked on M1 (PR #9).
**Scope:** six deepenings from the architecture review of 2026-09-12, on one branch stacked on the M1 branch, one PR.
**Vocabulary:** module, interface, seam, adapter, depth, leverage, locality as in Matt Pocock's codebase-design skill; domain terms as in `CONTEXT.md`.

## Why

An architecture review of the repository (five explorers, 23 candidates, merged into ten) found that the ideas M1 made central are still computed in several places each:

- **The plan** — one effect per point — is derived five times: `split_by_confidence`, `plan_markdown`, `decisions_markdown`, `as_effects` and the effect eval's `effects_from`. Two of them write fields into the dicts they are given, and the eval deep-copies and un-stamps to undo it. The Board plan tab and the caption over the Apply button already count the same plan differently ("ask a human 2, decisions 2" against "ask a human 4").
- **The effect key** is split over three places — which fields feed it (`src/apply.py`), how it is hashed (`src/idempotency.py`), and the n8n Idempotency check node — and nothing tests that the Python side and the node agree. They do not: a null description keys as "None" in Python and as "" in the node, and a few whitespace characters normalise differently.
- **The idempotency store** exposes three calls and an ordering rule that lives only in a docstring, so every caller writes the protocol by hand, and an in-batch duplicate of a failed effect is reported as "already applied".
- **The decision eval** still carries its own copy of the match call (board text and reply parsing), the same kind of copy that drifted twice before.
- **ClickUp requests** are made at nine sites that each handle a different subset of token, status, JSON and network errors; a network error during Apply escapes as a traceback.
- **"Decision"** means a meeting decision, the agent's match, and (in M5's design) a person's verdict.

## Binding constraints

- No file in `prompts/` changes, and the shape of what the model returns does not change. The measurement stop of 2026-08-20 stands.
- The evals keep calling production code, and their published numbers stay comparable: the model sees byte-identical input, and routing rules do not change.
- Effect keys stay byte-compatible with the n8n Idempotency check node for every input the node can receive; the three existing reference vectors keep their keys. The n8n export is not changed, so the live instance needs no re-import.
- Persisted formats do not change: the records in `state/processed_effects.jsonl`, `evals/effect_decisions.json`, `evals/decision_log.jsonl`, and the `DECISION:` line of the match reply.
- One scope per run. No tracker seam (M3's, with a second adapter), no packaging or settings (M2), no model seam (M4).
- Python 3.9 compatible; offline tests only; test-first at the seams listed below.

## The deepenings, in order

Each is one ticket and one commit series; each ends green; later ones build on earlier ones.

### 1. The effect key is one module, pinned against the n8n node

One module answers "what is this effect's key": which text a point contributes (its name and body, defined once for every shape of point), the None-safe and whitespace rules, and the hash. `create_key`, `comment_key` and `comment_body` move out of `src/apply.py`. The name and body of a point are defined by one function that `reconcile`, `reconcile_decisions`, the key and the effect eval all use.

**Seam under test:** the key of an effect, exercised through a parity test that runs the n8n Idempotency check node's own JavaScript under Node against items shaped exactly as `reconcile()` produces them, and asserts Python's key equals the node's — including a null description, a body taken from `detail`, and whitespace characters on which Python's `\s` and JavaScript's `\s` differ. The tautological parity test in `tests/test_apply.py` is deleted, not kept beside it.

### 2. The decision eval calls the production match step

`evals/eval_decisions.py` loses `BOARD_TEXT`, `BOARD_IDS` and its private `decide()`, and calls `reconcile.decide_one`. The model input is byte-identical for the ground-truth board (it carries only ids and names), so the published numbers stay comparable and nothing is re-measured.

**Seam under test:** the eval's per-point call, with the model client replaced by a recorder, asserting the prompt and system text the eval sends equal production's for every ground-truth point.

### 3. The plan is one value

A new `src/plan.py` builds the plan once, without touching its inputs: from the task matches, the meeting-decision matches, the board, the scope and the gate, it returns a plan holding every effect with its point, effect kind, intent, target row, confidence, reason, escalation cause and source (task or meeting decision), plus the scope it was reconciled against. The Board plan Markdown, the CLI's counts, the app's caption and checkboxes, `apply_plan` and the effect eval all read that value. `split_by_confidence`, `as_effects`, the gate inside `decisions_markdown`, and the deep-copy-and-unstamp code in the effect eval are deleted. `apply_plan` takes the plan and the points a person ticked, and writes only to the plan's scope — the environment fallback for the list goes.

**Seam under test:** the plan builder (routing through the gate, the guardrail causes surviving, a meeting decision never becoming a create, a meeting decision with no target asking with no intent, inputs left untouched) and the plan renderer; `apply_plan` through its interface with the tracker calls faked at the ClickUp module's edge. Tests pinned to the old workaround are deleted.

### 4. The idempotency store runs an effect at most once

The store gains one operation that reserves a key, runs the effect, commits on success, releases the reservation on failure, and reports applied, already applied, repeated in this batch, or failed. `apply_plan` and the public no-API demo both call it. The store resolves its own file from `WB_HOME` when set, falling back to the repository root, as the n8n nodes do. The JSONL record format is unchanged.

**Seam under test:** the store's once operation against a temporary file: a second run applies nothing, a failure leaves no key and does not block a later identical effect, a repeat inside one batch is reported as a repeat.

### 5. One ClickUp request path

`src/clickup.py` gains one private request function that owns the token, headers, timeout, network errors, non-2xx responses and non-JSON bodies; all nine request sites go through it, and `get_members` moves in from `src/assignees.py`, which keeps only the pure name resolution. Reads raise `WorkbenchError`; writes return `(False, reason)`. The app shows a failing list read as a failure, not as "no list configured". `push_tasks`, which has no caller, is deleted.

**Seam under test:** the ClickUp module's public functions, with the HTTP transport faked at the one request function's edge (`requests`), covering a 401, a network error, a 200 with a non-JSON body, and a failed comment during apply returning a reason instead of raising.

### 6. "Decision" splits into meeting decision, match and verdict

The code-side names that carry the match sense are renamed to the glossary: `parse_decision`, `decide_one`, `reconcile_decisions` and `decisions_markdown`, the `decisions` / `decided` variables and the app's result keys, the eval's `decided`. Every pinned spelling stays: the `DECISION:` reply line, the `decision` field in stored match records and the decision log, the `decisions` key in `evals/effect_decisions.json`.

**Seam under test:** none new — behaviour does not change; the whole suite is the check, and a grep for the old identifiers outside pinned formats comes back empty.

## Deferred, with where they go

- **One pipeline run module behind the CLI and the app** — to the M2 plan; it is the natural home for M2's entry points and settings, and it needs a model seam for tests.
- **A tracker port under apply** — to M3; with only ClickUp behind it the seam would be hypothetical.
- **A model port with a scripted adapter** — to M4, which reworks the model client.
- **One team roster per run** — to M3.

## Tracking

One parent issue in the WB team and one sub-issue per deepening, blocking in the order above (2 is independent and may land first).
