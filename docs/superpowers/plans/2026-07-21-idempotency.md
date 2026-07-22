# Idempotency Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Re-processing the same meeting must not create duplicate ClickUp tasks or comments — a deterministic idempotency guard keyed on the applied effect.

**Architecture:** A small Python core (`src/idempotency.py`: `normalize`, `effect_key`, `IdempotencyStore`) is the source of truth, tested with pytest and demoable via a no-API CLI. The same key spec is mirrored byte-for-byte into three n8n Code/IF nodes inserted into the sync workflow (`check` before applying, `filter` to drop duplicates, `mark` after a successful apply). Python↔n8n parity is pinned by reference vectors.

**Tech Stack:** Python 3.9 (`.venv`), pytest (new dev dependency), n8n Code nodes (Node.js `crypto` + `fs`), ClickUp REST API (already wired).

## Global Constraints

- Python target **3.9** (`.venv/bin/python`). Every new `.py` module starts with `from __future__ import annotations`.
- **Normalization order is fixed:** lowercase → collapse every `\s+` run to a single space → trim. Python `re.sub(r"\s+", " ", text.lower()).strip()`; JS `text.toLowerCase().replace(/\s+/g, " ").trim()`.
- **Key spec (must be byte-identical Python and JS):** `key = sha1(payload, utf-8).hexdigest()`. UPDATE payload `"UPDATE|<target_task_id>|<normalized comment>"`. NEW payload `"NEW|<normalized (title + ' ' + description)>"`.
- **Write the key only AFTER a successful side effect.** Never before applying.
- **Store** is append-only JSONL at `state/processed_effects.jsonl` — git-ignored (runtime state); a committed `state/processed_effects.example.jsonl` shows the record shape.
- **n8n launch** for these nodes requires `NODE_FUNCTION_ALLOW_BUILTIN=fs,crypto` (currently only `fs`).
- **Reference vectors (verified, verbatim):**
  - `normalize("  Saved   cards\n unblocked ")` == `"saved cards unblocked"`
  - `effect_key("UPDATE", "86eyay0p7", "Saved cards feature unblocked")` == `48c7e738b2b8911f66739a32236f6e0af99c1ebf`
  - `effect_key("UPDATE", "86ey9z6rc", "Crash fix in code review")` == `ea4e60440d94fb037f741c56f4377c2e26a420c8`
  - `effect_key("NEW", "", "Investigate iOS checkout funnel  Pull session data and find where users drop off")` == `cc2e2b757a17de13322942c6229404f2305a30ba`
- **Commits:** short imperative English subject; end body with `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`. Run git from the project root.

---

## File Structure

**New:**
- `src/idempotency.py` — the core (`normalize`, `effect_key`, `IdempotencyStore`) + a no-API `__main__` demo.
- `tests/test_idempotency.py` — pytest suite.
- `tests/idempotency_vectors.json` — pinned input→sha1 vectors (Python↔n8n parity).
- `state/processed_effects.example.jsonl` — one committed sample record (also ensures `state/` exists for the n8n fs-append).
- `requirements-dev.txt` — pytest (dev-only, kept out of the runtime requirements).

**Modified:**
- `.gitignore` — ignore the real `state/processed_effects.jsonl`.
- `n8n/meeting-to-clickup-sync.workflow.json` — sanitized copy with the new nodes.
- Live n8n workflow `id=SyncMeetingCU001` — same nodes, via export→patch→import.
- `docs/n8n-case.html` + Notion spec ("Workbench" page) — the idempotency section.

---

## Task 1: Core key functions (`normalize`, `effect_key`)

**Files:**
- Create: `src/idempotency.py`
- Create: `tests/test_idempotency.py`
- Create: `tests/idempotency_vectors.json`
- Create: `requirements-dev.txt`

**Interfaces:**
- Consumes: nothing (leaf module; stdlib only — `hashlib`, `re`, `json`, `pathlib`).
- Produces:
  - `normalize(text: str) -> str`
  - `effect_key(kind: str, target: str, content: str) -> str` — `kind ∈ {"UPDATE","NEW"}`, returns 40-char sha1 hex.

- [ ] **Step 1: Add the dev dependency and install pytest**

Create `requirements-dev.txt`:
```
pytest>=8.0
```
Run:
```bash
.venv/bin/pip install -r requirements-dev.txt
```
Expected: `Successfully installed pytest-8.x ...`

- [ ] **Step 2: Pin the reference vectors**

Create `tests/idempotency_vectors.json` (these exact values are asserted by both pytest and, later, the n8n node):
```json
{
  "normalize": [
    {"in": "  Saved   cards\n unblocked ", "out": "saved cards unblocked"},
    {"in": "iOS", "out": "ios"}
  ],
  "effect_key": [
    {"kind": "UPDATE", "target": "86eyay0p7", "content": "Saved cards feature unblocked", "key": "48c7e738b2b8911f66739a32236f6e0af99c1ebf"},
    {"kind": "UPDATE", "target": "86ey9z6rc", "content": "Crash fix in code review", "key": "ea4e60440d94fb037f741c56f4377c2e26a420c8"},
    {"kind": "NEW", "target": "", "content": "Investigate iOS checkout funnel  Pull session data and find where users drop off", "key": "cc2e2b757a17de13322942c6229404f2305a30ba"}
  ]
}
```

- [ ] **Step 3: Write the failing test**

Create `tests/test_idempotency.py`:
```python
from __future__ import annotations

import json
from pathlib import Path

from src.idempotency import effect_key, normalize

VECTORS = json.loads(
    (Path(__file__).resolve().parent / "idempotency_vectors.json").read_text(encoding="utf-8")
)


def test_normalize_vectors():
    for case in VECTORS["normalize"]:
        assert normalize(case["in"]) == case["out"]


def test_normalize_handles_none():
    assert normalize(None) == ""


def test_effect_key_matches_pinned_vectors():
    for case in VECTORS["effect_key"]:
        assert effect_key(case["kind"], case["target"], case["content"]) == case["key"]


def test_new_and_update_keys_differ_for_same_text():
    assert effect_key("NEW", "", "ship it") != effect_key("UPDATE", "t1", "ship it")


def test_update_key_depends_on_target():
    assert effect_key("UPDATE", "t1", "x") != effect_key("UPDATE", "t2", "x")
```

- [ ] **Step 4: Run the test to verify it fails**

Run:
```bash
.venv/bin/python -m pytest tests/test_idempotency.py -q
```
Expected: FAIL — `ModuleNotFoundError: No module named 'src.idempotency'`.

- [ ] **Step 5: Write the minimal implementation**

Create `src/idempotency.py`:
```python
#!/usr/bin/env python3
"""Idempotency for the meeting -> ClickUp sync.

Deterministic guard so re-processing the same meeting does not create
duplicate tasks or comments. Keyed on the *applied effect* (an UPDATE comment
on a task, or a NEW task), computed after the Match agent's decision.

The key spec is mirrored byte-for-byte in the n8n "Idempotency check" and
"Mark processed" Code nodes; tests/idempotency_vectors.json pins the parity.
"""

from __future__ import annotations

import hashlib
import re


def normalize(text: str) -> str:
    """Lowercase, collapse any whitespace run to one space, then trim."""
    return re.sub(r"\s+", " ", (text or "").lower()).strip()


def effect_key(kind: str, target: str, content: str) -> str:
    """SHA-1 hex of the effect payload. kind is "UPDATE" or "NEW".

    UPDATE: "UPDATE|<target_task_id>|<normalized comment>"
    NEW:    "NEW|<normalized title + ' ' + description>"
    """
    if kind == "UPDATE":
        payload = f"UPDATE|{target}|{normalize(content)}"
    else:
        payload = f"NEW|{normalize(content)}"
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()
```

- [ ] **Step 6: Run the test to verify it passes**

Run:
```bash
.venv/bin/python -m pytest tests/test_idempotency.py -q
```
Expected: PASS — 5 passed.

- [ ] **Step 7: Commit**

```bash
git add src/idempotency.py tests/test_idempotency.py tests/idempotency_vectors.json requirements-dev.txt
git commit -m "Add idempotency key core (normalize + effect_key) with pinned vectors"
```

---

## Task 2: `IdempotencyStore`

**Files:**
- Modify: `src/idempotency.py` (append the class)
- Modify: `tests/test_idempotency.py` (append tests)

**Interfaces:**
- Consumes: `effect_key` from Task 1.
- Produces:
  - `IdempotencyStore(path: Path)`
  - `.is_duplicate(key: str) -> bool` — committed OR reserved this run
  - `.mark_seen(key: str) -> None` — reserve in the current run, before applying
  - `.commit(key: str, meta: dict) -> None` — append a record; call only after a successful effect

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_idempotency.py`:
```python
from src.idempotency import IdempotencyStore


def test_store_empty_is_not_duplicate(tmp_path):
    store = IdempotencyStore(tmp_path / "s.jsonl")
    assert store.is_duplicate("abc") is False


def test_commit_makes_key_duplicate_and_persists(tmp_path):
    p = tmp_path / "s.jsonl"
    store = IdempotencyStore(p)
    store.commit("abc", {"kind": "NEW", "preview": "x"})
    assert store.is_duplicate("abc") is True
    # a fresh instance reads the committed key back from disk
    assert IdempotencyStore(p).is_duplicate("abc") is True


def test_mark_seen_catches_second_in_same_batch(tmp_path):
    store = IdempotencyStore(tmp_path / "s.jsonl")
    assert store.is_duplicate("k") is False
    store.mark_seen("k")            # first effect, not yet applied/committed
    assert store.is_duplicate("k") is True  # second identical effect in the batch


def test_malformed_line_is_ignored(tmp_path):
    p = tmp_path / "s.jsonl"
    p.write_text('{"key": "good"}\nnot json\n{"nokey": 1}\n', encoding="utf-8")
    store = IdempotencyStore(p)
    assert store.is_duplicate("good") is True
```

- [ ] **Step 2: Run to verify it fails**

Run:
```bash
.venv/bin/python -m pytest tests/test_idempotency.py -q
```
Expected: FAIL — `ImportError: cannot import name 'IdempotencyStore'`.

- [ ] **Step 3: Implement the class**

Append to `src/idempotency.py` (add `import json` and `from pathlib import Path` to the existing imports at the top):
```python
class IdempotencyStore:
    """Append-only JSONL store of applied-effect keys.

        store = IdempotencyStore(Path("state/processed_effects.jsonl"))
        key = effect_key("UPDATE", target_id, comment)
        if store.is_duplicate(key):
            skip()
        else:
            store.mark_seen(key)   # reserve before applying (in-batch dedup)
            apply_effect()         # the side effect
            store.commit(key, {...})  # record only after success
    """

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._committed: set[str] = set()
        self._seen_this_run: set[str] = set()
        if self.path.exists():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    self._committed.add(json.loads(line)["key"])
                except (json.JSONDecodeError, KeyError):
                    continue  # tolerate a bad line, never crash the run

    def is_duplicate(self, key: str) -> bool:
        return key in self._committed or key in self._seen_this_run

    def mark_seen(self, key: str) -> None:
        self._seen_this_run.add(key)

    def commit(self, key: str, meta: dict) -> None:
        """Append the key record. Call ONLY after a successful effect."""
        self._committed.add(key)
        self._seen_this_run.discard(key)
        record = {"key": key, **meta}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
```
Update the top-of-file imports so the module reads:
```python
import hashlib
import json
import re
from pathlib import Path
```

- [ ] **Step 4: Run to verify it passes**

Run:
```bash
.venv/bin/python -m pytest tests/test_idempotency.py -q
```
Expected: PASS — 9 passed.

- [ ] **Step 5: Commit**

```bash
git add src/idempotency.py tests/test_idempotency.py
git commit -m "Add IdempotencyStore (persist, in-batch dedup, commit-after-success)"
```

---

## Task 3: The core invariant + no-API demo + store plumbing

**Files:**
- Modify: `src/idempotency.py` (add demo helpers + `__main__`)
- Modify: `tests/test_idempotency.py` (add the double-run invariant test)
- Create: `state/processed_effects.example.jsonl`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: `effect_key`, `IdempotencyStore` from Tasks 1–2; reads `evals/decision_log.jsonl` as a fixture.
- Produces:
  - `effects_from_log(path: Path) -> list[tuple[str, str, str]]` — `(kind, target, content)` per logged decision
  - `apply_batch(effects, store) -> tuple[int, int]` — returns `(applied, skipped)`, mirrors the n8n mark→apply→commit order

- [ ] **Step 1: Write the failing invariant test**

Append to `tests/test_idempotency.py`:
```python
from src.idempotency import apply_batch, effects_from_log


def test_second_run_applies_nothing(tmp_path):
    effects = [("UPDATE", "t1", "saved cards unblocked"),
               ("NEW", "", "investigate ios funnel"),
               ("UPDATE", "t2", "crash fix in review")]
    store = IdempotencyStore(tmp_path / "s.jsonl")
    applied1, skipped1 = apply_batch(effects, store)
    applied2, skipped2 = apply_batch(effects, store)
    assert (applied1, skipped1) == (3, 0)
    assert (applied2, skipped2) == (0, 3)


def test_duplicate_within_one_batch_applied_once(tmp_path):
    effects = [("UPDATE", "t1", "same"), ("UPDATE", "t1", "same")]
    store = IdempotencyStore(tmp_path / "s.jsonl")
    applied, skipped = apply_batch(effects, store)
    assert (applied, skipped) == (1, 1)
```

- [ ] **Step 2: Run to verify it fails**

Run:
```bash
.venv/bin/python -m pytest tests/test_idempotency.py -q
```
Expected: FAIL — `ImportError: cannot import name 'apply_batch'`.

- [ ] **Step 3: Implement the demo helpers + `__main__`**

Append to `src/idempotency.py`:
```python
def effects_from_log(path: Path) -> list:
    """Read evals/decision_log.jsonl into (kind, target, content) effects.

    Uses the logged `point` as the content — enough to demonstrate the
    deterministic guard without any API call.
    """
    effects = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        d = json.loads(line)
        if d.get("decision") == "UPDATE":
            effects.append(("UPDATE", d.get("target") or "", d.get("point") or ""))
        else:
            effects.append(("NEW", "", d.get("point") or ""))
    return effects


def apply_batch(effects: list, store: "IdempotencyStore") -> tuple:
    """Mark-then-apply, mirroring the n8n check -> filter -> apply -> mark order.

    Phase 1 marks fresh effects (in-batch dedup); phase 2 "applies" them (no
    real side effect here) and commits the key only after that apply.
    """
    fresh = []
    skipped = 0
    for kind, target, content in effects:
        key = effect_key(kind, target, content)
        if store.is_duplicate(key):
            skipped += 1
        else:
            store.mark_seen(key)
            fresh.append((key, kind, target, content))
    applied = 0
    for key, kind, target, content in fresh:
        store.commit(key, {"kind": kind, "target": target or None, "preview": content[:60]})
        applied += 1
    return applied, skipped


def _demo() -> None:
    import tempfile

    root = Path(__file__).resolve().parent.parent
    effects = effects_from_log(root / "evals" / "decision_log.jsonl")
    with tempfile.TemporaryDirectory() as d:
        store = IdempotencyStore(Path(d) / "demo.jsonl")
        a1, s1 = apply_batch(effects, store)
        a2, s2 = apply_batch(effects, store)
    print(f"effects in the meeting: {len(effects)}")
    print(f"run 1:  applied={a1}  skipped={s1}")
    print(f"run 2:  applied={a2}  skipped={s2}")
    print(f"\nIdempotent: the second run applied {a2} new effects "
          f"(re-processing the same meeting is a no-op).")


if __name__ == "__main__":
    _demo()
```

- [ ] **Step 4: Run to verify the tests pass**

Run:
```bash
.venv/bin/python -m pytest tests/test_idempotency.py -q
```
Expected: PASS — 11 passed.

- [ ] **Step 5: Run the demo (no API) and verify the proof**

Run:
```bash
.venv/bin/python src/idempotency.py
```
Expected output (8 decisions in the current log):
```
effects in the meeting: 8
run 1:  applied=8  skipped=0
run 2:  applied=0  skipped=8

Idempotent: the second run applied 0 new effects (re-processing the same meeting is a no-op).
```

- [ ] **Step 6: Add the committed example record and gitignore the real store**

Create `state/processed_effects.example.jsonl`:
```
{"key": "48c7e738b2b8911f66739a32236f6e0af99c1ebf", "kind": "UPDATE", "target": "86eyay0p7", "preview": "saved cards unblocked", "ts": "2026-07-21T18:00:00.000Z", "source": "transcript_followup"}
```
Append to `.gitignore` (after the `outputs/` line):
```
state/processed_effects.jsonl
```

- [ ] **Step 7: Verify the ignore rule works**

Run:
```bash
printf '{"key":"tmp"}\n' > state/processed_effects.jsonl
git status --short state/
```
Expected: only `state/processed_effects.example.jsonl` shows as untracked; `state/processed_effects.jsonl` does NOT appear. Then clean up:
```bash
rm state/processed_effects.jsonl
```

- [ ] **Step 8: Commit**

```bash
git add src/idempotency.py tests/test_idempotency.py state/processed_effects.example.jsonl .gitignore
git commit -m "Prove idempotency invariant (double-run = 0 applied) + no-API demo"
```

---

## Task 4: Wire idempotency into the n8n sync workflow

This task is verified by an end-to-end run, not pytest. Use the auto branch only (no Telegram/tunnel needed): temporarily force the `Confident?` gate so everything routes to auto, run twice, and confirm the second run is a no-op.

**Files:**
- Modify: live workflow `id=SyncMeetingCU001` (via export→patch→import)
- Modify: `n8n/meeting-to-clickup-sync.workflow.json` (sanitized copy in the repo)

**Interfaces:**
- Consumes: the key spec + normalization from the Global Constraints (mirrored in JS).
- Produces: three logical nodes — `Idempotency check` (Run Once for All Items), `Fresh only` (IF), `Mark processed` (two twins: auto + appr, mirroring the existing `Add comment` auto/appr split).

- [ ] **Step 1: Stop n8n so the CLI can touch the SQLite DB cleanly**

```bash
pkill -f "n8n" ; sleep 2 ; echo "stopped"
```

- [ ] **Step 2: Export the live workflow**

```bash
cd ~/"Job Search/ai-product-ops-workbench"
npx n8n export:workflow --id=SyncMeetingCU001 --output=/tmp/sync_export.json
```
Expected: `Successfully exported 1 workflow.`

- [ ] **Step 3: Patch the workflow JSON with a script**

Create `/tmp/patch_sync.py` and run it. It adds the nodes and rewires the connections described above. The n8n JS for each node is embedded here verbatim.

```python
import json, sys

WF = "/tmp/sync_export.json"
data = json.load(open(WF))
wf = data[0] if isinstance(data, list) else data
nodes = wf["nodes"]
conns = wf["connections"]

CHECK_JS = r'''
const fs = require('fs');
const crypto = require('crypto');
const STORE = 'state/processed_effects.jsonl';
function normalize(t){return (t||'').toLowerCase().replace(/\s+/g,' ').trim();}
function effectKey(kind,target,content){
  const payload = kind==='UPDATE' ? ('UPDATE|'+target+'|'+normalize(content))
                                  : ('NEW|'+normalize(content));
  return crypto.createHash('sha1').update(payload,'utf8').digest('hex');
}
let committed = new Set();
try {
  for (const line of fs.readFileSync(STORE,'utf8').split('\n')) {
    const s = line.trim(); if(!s) continue;
    try { committed.add(JSON.parse(s).key); } catch(e){}
  }
} catch(e) { /* no store yet */ }
const seen = new Set();
const out = [];
for (const it of items) {
  const j = it.json;
  const kind = j.is_update ? 'UPDATE' : 'NEW';
  const content = j.is_update ? (j.comment||'')
                              : (((j.name||'')+' '+(j.description||'')).trim());
  const key = effectKey(kind, j.target_id||'', content);
  const is_duplicate = committed.has(key) || seen.has(key);
  if (!is_duplicate) seen.add(key);
  out.push({ json: Object.assign({}, j, { idem_key: key, is_duplicate }) });
}
return out;
'''.strip()

MARK_JS = r'''
const fs = require('fs');
const j = $json;
if (j.idem_key) {
  const rec = {
    key: j.idem_key,
    kind: j.is_update ? 'UPDATE' : 'NEW',
    target: j.target_id || null,
    preview: (j.name || '').slice(0,60),
    ts: new Date().toISOString(),
    source: 'sync'
  };
  fs.appendFileSync('state/processed_effects.jsonl', JSON.stringify(rec) + '\n');
}
return { json: j };
'''.strip()

def add_node(name, ntype, params, pos, type_version=2):
    node = {
        "parameters": params,
        "id": name.lower().replace(" ", "-").replace("(", "").replace(")", ""),
        "name": name,
        "type": ntype,
        "typeVersion": type_version,
        "position": pos,
    }
    nodes.append(node)
    return node

# 1. Idempotency check — runs once for all items (needs the whole batch for in-batch dedup)
add_node("Idempotency check", "n8n-nodes-base.code",
         {"mode": "runOnceForAllItems", "jsCode": CHECK_JS}, [-40, 480])
# 2. Fresh only — IF is_duplicate === false
add_node("Fresh only", "n8n-nodes-base.if", {
    "conditions": {"options": {"caseSensitive": True, "typeValidation": "strict"},
        "combinator": "and",
        "conditions": [{"leftValue": "={{ $json.is_duplicate }}",
                        "rightValue": False,
                        "operator": {"type": "boolean", "operation": "false"}}]}
}, [180, 480])
# 3. Mark processed twins
add_node("Mark processed (auto)", "n8n-nodes-base.code", {"jsCode": MARK_JS}, [1180, 300])
add_node("Mark processed (appr)", "n8n-nodes-base.code", {"jsCode": MARK_JS}, [1180, 640])

def set_conn(src, targets, out_index=0):
    conns.setdefault(src, {}).setdefault("main", [])
    main = conns[src]["main"]
    while len(main) <= out_index:
        main.append([])
    main[out_index] = [{"node": t, "type": "main", "index": 0} for t in targets]

# Rewire the head: Parse decision -> Idempotency check -> Log decision -> Fresh only -> Confident?
set_conn("Parse decision", ["Idempotency check"])
set_conn("Idempotency check", ["Log decision"])
set_conn("Log decision", ["Fresh only"])
set_conn("Fresh only", ["Confident?"], out_index=0)  # IF true output
set_conn("Fresh only", [], out_index=1)              # IF false output = drop (already logged)

# Rewire the tails: applies -> Mark processed
set_conn("Add comment (auto)", ["Mark processed (auto)"])
set_conn("Create task (auto)", ["Mark processed (auto)"])
set_conn("Add comment (appr)", ["Mark processed (appr)"])
set_conn("Create task (appr)", ["Mark processed (appr)"])
set_conn("Mark processed (appr)", ["Confirm done (Telegram)"])

json.dump(data, open(WF, "w"), ensure_ascii=False, indent=2)
print("patched:", WF)
```
Run:
```bash
.venv/bin/python /tmp/patch_sync.py
```
Expected: `patched: /tmp/sync_export.json`

- [ ] **Step 4: Add `idem_key`/`duplicate` to the existing `Log decision` node**

In `/tmp/sync_export.json`, find the `Log decision` node's `jsCode` and extend the `entry` object with two fields so skipped duplicates are auditable. Change:
```javascript
  gate: (j.confidence >= 0.8) ? 'auto' : 'human'
```
to:
```javascript
  gate: (j.confidence >= 0.8) ? 'auto' : 'human',
  idem_key: j.idem_key || null,
  duplicate: !!j.is_duplicate
```
(Do this with a small Python replace or by hand; re-save the file.)

- [ ] **Step 5: Import the patched workflow back**

```bash
npx n8n import:workflow --input=/tmp/sync_export.json
```
Expected: `Successfully imported 1 workflow.`

- [ ] **Step 6: Start n8n with both builtins allowed**

```bash
cd ~/"Job Search/ai-product-ops-workbench"
NODE_FUNCTION_ALLOW_BUILTIN=fs,crypto N8N_DIAGNOSTICS_ENABLED=false npx n8n start >/tmp/n8n.log 2>&1 &
sleep 25 ; grep -i "editor is now accessible" /tmp/n8n.log || tail -5 /tmp/n8n.log
```
Expected: n8n reports it is up on `localhost:5678`.

- [ ] **Step 7: Force the auto branch for the test**

In the n8n UI (localhost:5678) open `Meeting → ClickUp (sync…)`, open `Confident?`, and temporarily set the threshold so the condition is always true (e.g. `confidence >= -1`). Save. (This is the same "threshold −1" trick used to validate stage 3 without the Telegram tunnel.) Ensure `state/processed_effects.jsonl` does not exist yet:
```bash
rm -f state/processed_effects.jsonl
```

- [ ] **Step 8: First end-to-end run**

```bash
npx n8n execute --id=SyncMeetingCU001
wc -l state/processed_effects.jsonl
```
Expected: the run creates comments/tasks in ClickUp; `state/processed_effects.jsonl` now has one line per applied effect (e.g. 6). Note the current comment/task counts on the ClickUp "AI Workbench Demo" list.

- [ ] **Step 9: Second end-to-end run — the idempotency proof**

```bash
npx n8n execute --id=SyncMeetingCU001
wc -l state/processed_effects.jsonl
```
Expected: **0 duplicate comments on the repeated (UPDATE) items and 0 duplicate tasks** in ClickUp; `state/processed_effects.jsonl` line count is unchanged for those UPDATE items. Caveat per the spec: an item that was NEW in run 1 now exists, so the Match agent picks UPDATE and posts one comment on it (its key changed NEW→UPDATE); from a third run on that is suppressed too. Confirm by inspecting the ClickUp list and `evals/decision_log.jsonl` (duplicates show `"duplicate": true`).

- [ ] **Step 10: Restore the real threshold**

In the UI set `Confident?` back to `confidence >= 0.8` and save. (Optional: re-run once via CLI to confirm auto/HITL split still works.)

- [ ] **Step 11: Refresh the sanitized copy in the repo**

```bash
npx n8n export:workflow --id=SyncMeetingCU001 --output=/tmp/sync_clean.json
```
Then sanitize into `n8n/meeting-to-clickup-sync.workflow.json`, matching how the existing file was sanitized: strip credentials/`credentials` blocks, replace any real `chat_id` with a placeholder, and keep the store path relative (`state/processed_effects.jsonl`). Diff against the previous committed version to confirm only the three new nodes + rewired connections + the `Log decision` two-field change appear.

- [ ] **Step 12: Commit**

```bash
git add n8n/meeting-to-clickup-sync.workflow.json
git commit -m "Wire idempotency guard into the n8n board-sync workflow"
```

---

## Task 5: Package the story (case page + Notion + memory)

**Files:**
- Modify: `docs/n8n-case.html`
- Modify: Notion "Workbench" spec page (id `3a4dc346fa6180ada2fcf5926253b662`)
- Modify: memory file `ai-product-ops-workbench.md`

**Interfaces:**
- Consumes: the verified behavior from Task 4.
- Produces: an "Idempotency (two layers of protection)" section, consistent with the existing case-page structure.

- [ ] **Step 1: Add the idempotency section to `docs/n8n-case.html`**

Follow the page's existing section pattern (problem → mechanism → result → guardrails). Content to include, verbatim on the honest boundary:
- **Problem:** re-processing the same meeting re-adds comments and risks duplicate tasks.
- **Mechanism:** a deterministic idempotency key on the applied effect (`sha1` of UPDATE `target|comment` or NEW `title+description`), stored append-only; checked before applying, key written only after a successful effect; in-batch dedup for repeats inside one run.
- **Two layers:** deterministic key catches the exact/verbatim repeat; the semantic Match agent catches the rephrased repeat. Include the NEW→UPDATE re-run nuance.
- **Result:** running the same follow-up twice → 0 duplicate tasks, 0 duplicate comments on repeated items (proof: `python src/idempotency.py` → run 2 applies 0).

- [ ] **Step 2: Verify the case page renders**

```bash
open docs/n8n-case.html
```
Expected: the new section appears, styled like the others, no broken layout.

- [ ] **Step 3: Update the Notion "Workbench" spec**

Add an "Idempotency" block with the "🗣 how to say it in an interview" note: "I keyed the guard on the applied effect and wrote the key only after the side effect succeeds, so a retry never double-posts — and I was explicit that the hash handles exact repeats while the agent handles rephrased ones." Keep it in the existing doc voice.

- [ ] **Step 4: Update the project memory**

In `ai-product-ops-workbench.md`, update the status line: Tier 2 step 2 (idempotency) is DONE — core `src/idempotency.py` + pytest + no-API demo, three n8n nodes (check/filter/mark, key after success), store `state/processed_effects.jsonl` (gitignored), verified double-run = 0 duplicates. Note the n8n launch now needs `NODE_FUNCTION_ALLOW_BUILTIN=fs,crypto`. Point "next" to owners / summary delivery / Loom / distribution.

- [ ] **Step 5: Commit the repo docs**

```bash
git add docs/n8n-case.html
git commit -m "Package idempotency case: two layers, double-run proof"
```

---

## Self-Review

**Spec coverage:**
- Effect key (UPDATE/NEW), normalization, sha1 → Task 1. ✓
- Local JSONL store, load-into-set, commit-after-success, in-run dedup → Task 2. ✓
- Check-before / write-after, in-batch dedup, don't-go-silent (Log `duplicate`) → Tasks 2–4. ✓
- Python↔n8n parity via reference vectors → Task 1 (vectors) + Task 4 (same spec in JS). ✓
- 3-node n8n insertion (check/filter/mark), before `Confident?`, mark not on Reject → Task 4. ✓
- Tests: normalization, key stability, is_duplicate, commit-after-success, in-run dedup, double-run invariant → Tasks 1–3. ✓
- CLI no-API demo (the open spec item, now resolved as `__main__` on a decision_log fixture) → Task 3. ✓
- n8n end-to-end double run, sanitized copy refresh → Task 4. ✓
- Store is state not artifact: real gitignored, example committed → Task 3. ✓
- Packaging (case page, Notion) + two-layers honest boundary incl. NEW→UPDATE nuance → Task 5. ✓
- Out of scope (ClickUp signature) → correctly omitted. ✓

**Placeholder scan:** No TBD/TODO; all code blocks and sha1 vectors are concrete and verified. The one former open item (demo shape) is now fully specified in Task 3.

**Type consistency:** `normalize`, `effect_key(kind, target, content)`, `IdempotencyStore.is_duplicate/mark_seen/commit`, `effects_from_log`, `apply_batch` are named identically across tasks and tests. The n8n JS uses the same payload spec that produces the pinned vectors.
