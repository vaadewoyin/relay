# Targeted Gemini reliability review

The Phase 5 experiment remains 30/40 complete. This recovery set contains only its ten incomplete cases, with unchanged inputs, gold anchors, model and prompts. It ran once as a separate experiment. Nine completed. All three positive findings matched their expected kind and evidence, and the six completed negatives abstained. The distinct-pump negative returned malformed output. Median latency was 3.662 seconds and reported usage implies about $0.01214 at the standard rate.

Phase 5's six timeouts occurred at or near the 35-second end-to-end deadline. Extraction and semantic review share that deadline. A slow extraction can leave little time to launch the review request. The three unavailable classifications indicate HTTP 5xx or transport failures under the previous provider adapter. The Phase 5 records did not distinguish those causes. No rate-limit classification was recorded for the ten failures. The rejected request had no stored HTTP status or provider reason, so its exact cause remains unresolved.

Phase 6 adds the failing stage and numeric provider HTTP status to structured execution metadata. It retains the existing time, token, and retry limits. A timeout caught locally has no provider status. Provider messages and report contents remain excluded from logs. The first Phase 6 live walkthrough also encountered a rejected request after a 33.966-second extraction. That timing supports investigating the remaining deadline, but does not establish why the provider returned the rejection. No broad prompt or retry changes were made.

The original benchmark and separate recovery JSON are retained under local `artifacts/phase5/` and `artifacts/phase6/recovery.json`, respectively.
