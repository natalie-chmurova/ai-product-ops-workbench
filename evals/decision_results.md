# Agent-decision eval (board sync: new vs update) — 2026-08-18

Board: 7 tasks · points: 10 (6 true updates, 4 true new) · scored by exact match, 3 runs

| run | decision accuracy | target accuracy (updates) |
|---|---|---|
| 1 | 100% | 100% |
| 2 | 100% | 100% |
| 3 | 100% | 100% |

**Average: decision 100% · target 100%**

> **The harness had drifted; this run is the first on the real prompt.** Until
> 2026-08-18 this eval used its own copy of the match instruction and had fallen two
> rules behind `prompts/match.md` — that a decision the team reached is an UPDATE to the
> work it concerns, and that work someone is already doing is an UPDATE rather than a
> second copy. WB-11 had made that file the single source precisely so the module, the
> n8n node and this eval could not diverge; this eval never read it. The earlier 100% /
> 100% was therefore measuring an agent that shipped with rules the eval had never given
> it.
>
> **The score did not move — and that is a finding about the benchmark, not a clean
> bill of health.** None of the ten points exercises either added rule: there is no
> point where the team reaches a decision, and none where someone reports work they are
> already doing. So this set cannot tell "the new rules are harmless" apart from "the
> new rules are never reached". The number is now honest about *which* agent it
> describes; it still says nothing about the two rules themselves. Points that exercise
> them are the obvious next addition.
