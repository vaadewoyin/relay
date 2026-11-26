# Phase 3.1 live regression

Model `gemini-3.1-flash-lite`. The original dataset was kept unchanged. The v2 prompts were frozen before running the separate challenge set.

| Metric | Original v1 | Original v2 | Challenge v2 |
|---|---:|---:|---:|
| Completed cases | 22/22 | 20/22 | 8/8 |
| Precision | 10/13 | 9/10 | 3/3 |
| Recall on completed cases | 10/11 | 9/9 | 3/3 |
| Recall including failed executions | 10/11 | 9/11 | 3/3 |
| Negative false positives | 2/11 | 1/11 | 0/5 |
| Negative abstentions | 9/11 | 10/11 | 5/5 |
| Evidence validity | 100% | 100% | 100% |
| Schema validity of scored responses | 100% | 20/21 | 100% |
| Median latency | 5.782 s | 7.090 s | 10.127 s |
| Reported input/output tokens | 34,943 / 12,448 | 35,826 / 11,629 | 13,916 / 4,292 |
| Estimated cost | $0.0274077 | $0.0264000 | $0.0099173 |

The original compatible ownership case now abstained. The earlier ownership evidence-anchor miss resolved. One ambiguous-referent false positive remains. The unsupported completion case returned malformed output and the duplicate flood alarm case timed out. Those two cases count as misses in end-to-end recall. Cost covers reported usage only.

The original failure pattern pointed to treating report metadata as textual identity, collapsing a future action into a competing ownership claim, and quoting only fragments of a claim. The revised prompts ask for explicit identity, shared time, incompatible predicates, and a complete assertion in each citation. Keeping v2 favors review precision while acknowledging the lower end-to-end delivery rate in this single run. No evidence validator rule was made to infer semantics or suppress categories.

The local outputs are `artifacts/phase3/evaluation-live.json`, `artifacts/phase31/regression.json`, and `artifacts/phase31/challenge.json`. See the backend README for the repeatable live runner. Rates and latency are observations from small synthetic samples.
