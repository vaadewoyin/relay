# Relay design

Relay helps incoming facilities and hospitality maintenance staff review unresolved work, inspect original reports, and explicitly accept responsibility at shift change.

## Target workflow

1. Import shift reports from Notion and keep their original text, source IDs and links.
2. Show a short queue on Even G2. Deterministic checks flag missing owners, overdue actions and unresolved responsibilities. Gemini proposes contradictions and duplicate reports in a structured response.
3. Open Evidence Lens from a finding to read source excerpts. Reject proposals whose references or excerpts cannot be verified against the stored reports.
4. Preview what accepting responsibility will change, then require explicit confirmation from the incoming operator. Offer the same preview and confirmation for proposed voice updates.
5. In a single SQLite transaction, validate the operator and expected record version, deduplicate by operation ID, update ownership and persist a Handover Receipt with accepted and outstanding items. A stale version must trigger a refresh before retry.
6. Sync authorized changes back to Notion with a durable queue. Surface pending writes and guard against applying retries twice or overwriting edits observed since import.

## Failure behavior

If Gemini is unavailable, continue with deterministic findings and the original evidence. If Notion is unavailable, show the last successful sync time, use cached reports and queue authorized writes. Display stale-record conflicts for review. Keep a manual update path when voice is unavailable.

## Phase 0

The official starter displays a single event-capturing text container. A tap increments the count, scroll leaves it unchanged and a double tap invokes the exit flow. The product interaction design will be validated after this smoke check.
