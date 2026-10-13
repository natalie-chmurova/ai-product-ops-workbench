# n8n workflows

Three exports, in the order they were built. They are reference implementations of what
the Python pipeline does, not portable products. All three hardcode their demo
transcript and the ClickUp team, space and list ids of the demo workspace; the sync
workflow also carries ClickUp owner ids, and the two with Telegram carry `YOUR_CHAT_ID`
where your chat id goes. Those ids are my demo workspace's — put in your own team, space,
list and owner ids before the first run, then connect the credentials.

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
export NODE_FUNCTION_ALLOW_BUILTIN=fs,crypto
export N8N_BLOCK_ENV_ACCESS_IN_NODE=false
```

Set these before launching n8n. The `Log decision` node fails with a clear message
if `WB_HOME` is missing, rather than writing the log somewhere unexpected.

The sync workflow reads `WB_HOME` in three nodes — `Log decision`,
`Idempotency check` and `Mark processed` — so the decision log and the idempotency
store both live in the checkout, in the same files the Python app writes. The other
two workflows do not read it. Those nodes also `require` `fs`, and `Idempotency check`
`crypto`, which n8n allows only when `NODE_FUNCTION_ALLOW_BUILTIN` lists them.

They read `WB_HOME` through `$env`, and n8n 2.x blocks `$env` inside Code nodes unless
`N8N_BLOCK_ENV_ACCESS_IN_NODE` is exactly `false`; without it the run stops at the first
of them with "access to env vars denied". The trade-off: every Code node can then read
the n8n process's environment.

## Telegram approvals need a public address

`Ask approval (Telegram)` sends Approve / Reject buttons that link back to n8n's
waiting webhook. Telegram rejects a button whose link points at `localhost` — the run
stops at that node with *Bad Request: inline keyboard button URL ... is invalid: Wrong
HTTP URL* — so n8n has to be told a public address for its webhooks:

```bash
brew install cloudflared
cloudflared tunnel --url http://localhost:5678     # prints https://<random>.trycloudflare.com
export WEBHOOK_URL=https://<random>.trycloudflare.com/
export N8N_PROXY_HOPS=1                            # n8n now sits behind a proxy
```

Set both before starting n8n. A quick tunnel needs no Cloudflare account and gets a new
address every time it starts, so start it fresh with n8n each time. While it runs, the
n8n editor is reachable from the internet behind its login, and the approval links are
signed by n8n. Approvals sent through the localhost address worked as late as July 2026
and stopped being accepted by October.

## Keeping the prompt in sync

The `Match agent (Claude)` node carries `prompts/match.md`, rendered by
`scripts/sync_n8n_match_prompt.py`. Run it after editing the prompt, on the repo
export and on an exported copy of the live workflow; `tests/test_n8n_parity.py`
fails whenever the two differ.

## The confidence gate

The two `Confident?` IF nodes compare against a literal `0.8`, and the `Log decision`
node labels each decision `auto` or `human` with its own `>= 0.8`. The Python side keeps
the same number in `src.plan.GATE`; if one of the four moves, move the others.

## One approval per run

The approval branch asks about the first below-gate item of each run only. Telegram's
send-and-wait step sends one card and resumes with one item, so the other doubtful items
in that run are neither applied nor recorded as applied. A follow-up issue tracks looping
over them.
