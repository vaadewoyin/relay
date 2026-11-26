# Phase 5 live evaluation

Gemini `gemini-3.1-flash-lite`, `extract-v2`, and `semantic-review-v2` were frozen. The experiment attempted 40 distinct cases. It used the original 22 development cases, the eight previous challenge cases, and ten new held-out cases that were evaluated once. Historical results remain in [the Phase 3.1 record](results-v2.md).

| Metric | Development | Prior challenge | New holdout |
|---|---:|---:|---:|
| Completed / attempted | 19/22 | 4/8 | 7/10 |
| Finding precision | 9/10 | 2/2 | 5/5 |
| Finding recall, completed | 9/9 | 2/2 | 5/5 |
| Finding recall, all attempted | 9/11 | 2/3 | 5/5 |
| False-positive negative cases | 1/10 | 0/2 | 0/2 |
| Explicit negative abstentions | 9/10 | 2/2 | 2/2 |
| Valid evidence / emitted candidates | 10/10 | 2/2 | 5/5 |
| Schema validity of scored cases | 19/19 | 4/4 | 7/7 |
| Median completion latency | 5.590 s | 5.958 s | 6.741 s |
| Reported input / output tokens | 34,422 / 11,669 | 7,630 / 2,588 | 11,738 / 3,974 |
| Estimated standard API cost | $0.0261093 | $0.0057894 | $0.0088957 |

Across the three sets, 30 cases completed. Precision was 16/17, end-to-end recall was 16/19, and the case-level false-positive rate was 1/14 completed negatives. Total reported input and output tokens were 53,790 and 18,231, respectively. The estimated total was $0.0407944 based on reported usage. Actual billing may differ.

The ambiguous-referent false positive recurred on the development set. Gemini failed to complete six cases before the timeout, three with provider unavailability, and one with a rejected request. Two positive development cases and one positive challenge case missed delivery. Three negative holdout cases did not complete, including the misleading-quotation and injection cases. The two completed negative holdout cases abstained. The new holdout results cannot establish robustness on the uncompleted cases. The separate deterministic citation tests still cover invented text and unknown report IDs.

Finding precision and recall use one-to-one matches on kind and gold evidence anchors. Precision counts all validated findings on completed cases. End-to-end recall includes positive labels on attempted cases that failed. False-positive rate and abstention count completed negative cases. Schema validity measures complete structured cases among completed or malformed-output cases. Provider errors are listed separately. Evidence validity counts structurally valid citations among emitted candidates before deduplication, and a valid citation can still support an incorrect conclusion.

## Reproduce

Run from `backend/`, with a configured private `.env`:

```bash
uv run --locked --env-file .env python -m relay.intelligence.evaluate --live --limit 22 --pause 2 --output ../artifacts/phase5/development.json
uv run --locked --env-file .env python -m relay.intelligence.evaluate --live --dataset evals/facilities-challenge-v1.json --limit 8 --pause 2 --output ../artifacts/phase5/challenge.json
uv run --locked --env-file .env python -m relay.intelligence.evaluate --live --dataset evals/facilities-holdout-v1.json --limit 10 --pause 2 --output ../artifacts/phase5/holdout.json
```

The development run stopped after five cases on a rejected request. A continuation with `--offset 5 --limit 17` attempted the remaining cases and retained the first failure in the aggregate. The per-case JSON and `evaluation-summary.json` are under local `artifacts/phase5/`.
