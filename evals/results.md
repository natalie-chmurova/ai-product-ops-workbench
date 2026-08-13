# Extraction eval — 2026-08-13

Pipeline: `extract_context` → `build_tasks` · judge: LLM-as-judge (Claude) · 3 runs per transcript.

Recall is measured over MUST items only; debatable items never penalize recall but do protect precision. The messy transcripts exist so the benchmark can fail: a number that is always 100% measures nothing.

## Summary

| transcript | must / debatable | recall | precision |
|---|---|---|---|
| clean | 8 / 3 | 100% | 100% |
| messy 1 — reversed decision, ownerless item | 5 / 1 | 67% | 83% |
| messy 2 — noise, a task raised in passing, a hedged follow-up | 4 / 2 | 100% | 94% |

## clean

`samples/transcript_demo.txt` · ground truth `evals/ground_truth.json`

| run | tasks extracted | recall (must) | precision | missed |
|---|---|---|---|---|
| 1 | 10 | 100% | 100% | — |
| 2 | 10 | 100% | 100% | — |
| 3 | 10 | 100% | 100% | — |

**Average: recall 100% · precision 100%**

## messy 1 — reversed decision, ownerless item

`samples/transcript_messy_1.txt` · ground truth `evals/ground_truth_messy_1.json`

| run | tasks extracted | recall (must) | precision | missed |
|---|---|---|---|---|
| 1 | 3 | 60% | 100% | gt2, gt3 |
| 2 | 6 | 60% | 50% | gt2, gt3 |
| 3 | 4 | 80% | 100% | gt2 |

**Average: recall 67% · precision 83%**

## messy 2 — noise, a task raised in passing, a hedged follow-up

`samples/transcript_messy_2.txt` · ground truth `evals/ground_truth_messy_2.json`

| run | tasks extracted | recall (must) | precision | missed |
|---|---|---|---|---|
| 1 | 5 | 100% | 100% | — |
| 2 | 6 | 100% | 83% | — |
| 3 | 5 | 100% | 100% | — |

**Average: recall 100% · precision 94%**
