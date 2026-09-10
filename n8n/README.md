# n8n workflows

Three exports, in the order they were built. Each one is a complete workflow —
import the JSON into any n8n instance, connect the credentials, and run it.

| File | Workflow | What it adds |
|---|---|---|
| `meeting-to-clickup.workflow.json` | Meeting → ClickUp tasks | The straight line: transcript → Claude → ClickUp. Four nodes. |
| `meeting-to-clickup-hitl.workflow.json` | Meeting → ClickUp tasks (HITL) | A triage agent scores its own confidence. Confident calls go straight through; the rest are held for approval over Telegram. |
| `meeting-to-clickup-sync.workflow.json` | Meeting → ClickUp (sync) | Reads the board first, so a second run comments on the existing task instead of creating a duplicate. Logs every decision, and skips points it has already processed. |

## Importing

In n8n: **Workflows → Import from File**. Then open each credential-bearing
node and pick your own credentials — none are included in these exports.

Credentials used: **Anthropic** (all three), **ClickUp** (all three),
**Telegram** (HITL and sync).

## WB_HOME

The sync workflow appends one line per decision to `evals/decision_log.jsonl`,
which is what makes the calibration numbers in the case study reproducible.
Since n8n runs outside this repo, it needs to be told where the repo is:

```bash
export WB_HOME=/path/to/ai-product-ops-workbench
```

Set it before launching n8n. The `Log decision` node fails with a clear message
if it is missing, rather than writing the log somewhere unexpected.

The other two workflows do not read `WB_HOME` — only the sync one logs.

## The confidence gate

The two `Confident?` IF nodes compare against a literal `0.8`. The Python side keeps
the same number in `src.reconcile.GATE`; if one moves, move the other.
