# Relay design

Relay helps incoming facilities and hospitality maintenance staff review unresolved work, inspect original reports, and explicitly accept responsibility at shift change.

## Target workflow

1. Import shift reports from Notion and keep their original text, source IDs and links.
2. Show a short queue on Even G2. Deterministic checks flag missing owners, overdue actions and unresolved responsibilities. Exact duplicates and contradictions between structured observations are deterministic findings. A later AI layer can propose semantic matches and contradictions in a structured response.
3. Open Evidence Lens from a finding to read source excerpts. Reject proposals whose references or excerpts cannot be verified against the stored reports.
4. Preview what accepting responsibility will change, then require explicit confirmation from the incoming operator. Offer the same preview and confirmation for proposed voice updates.
5. In a single SQLite transaction, validate the operator and expected record version, deduplicate by operation ID, update ownership and persist a Handover Receipt with accepted and outstanding items. A stale version must trigger a refresh before retry.
6. Sync authorized changes back to Notion with a durable queue. Surface pending writes and guard against applying retries twice or overwriting edits observed since import.

## Failure behavior

If Gemini is unavailable, continue with deterministic findings and the original evidence. If Notion is unavailable, show the last successful sync time, use cached reports and queue authorized writes. Display stale-record conflicts for review. Keep a manual update path when voice is unavailable.

## Phase 0 verification

Phase 0 was accepted as **PASS**. Official Even Hub simulator 0.7.3 on WSLg rendered the Relay greeting, incremented the tap counter, preserved it on scroll in both directions, and received double tap. The double tap cleared the glasses framebuffer. The SDK confirmation dialog, physical G2 behavior, and physical package installation remain unverified.

## Phase 1 architecture

The [Python backend](../backend/README.md) uses a src layout with four boundaries. `domain.py` defines immutable Pydantic contracts and state transitions. `rules.py` contains pure integrity checks with an explicit observation clock. `service.py` coordinates commands through a small transaction interface. `store.py` owns SQLite, and `api.py` maps typed commands, responses, and errors to HTTP. This keeps business rules independently testable and lets integration tests use the same SQLite implementation as the demo.

Reports are immutable and retain exact source text and source IDs. Each finding carries at least one exact quote and a report ID. Duplicate reports share a source reference or equal whitespace-normalized text within the same asset and shift. Structured contradictions require the same asset and observation timestamp reported as operational and unavailable. Different timestamps can represent a real status change. Findings are historical observations and a review records one human decision. The engine checks overdue actions at intake and preview. It has no background scheduler.

Write commands deduplicate successful operations with a client UUID and payload fingerprint. SQLite WAL and an immediate write transaction cover the current-state check, write, and replay record. The handover preview captures unresolved work and its versions. Acceptance requires the incoming operator, explicit confirmation, and a matching snapshot. The same transaction transfers eligible work, increments versions, and saves a receipt with outstanding work. A stale command changes no report, action, or handover state. It can persist a finding for review.

SQLite stores typed records as JSON documents keyed by UUID. The service validates references within its transactions. This keeps the demo schema small, with scans intentionally scoped to a small local dataset. Before multi-site use, add indexed queries, pagination, durable migration tooling, and an authenticated identity boundary. Phase 1 uses a synthetic shift directory and supports status transitions and accepted responsibility transfer. General directory administration and manual action reassignment are outside this slice.

### Neural Maze references

- Adopted the API/UI boundary, FastAPI, uv and Ruff from the PhiloAgents engineering material. Relay keeps the FastAPI service separate from the existing wearable frontend and commits the dependency lockfile. [PhiloAgents](https://github.com/neural-maze/philoagents-course)
- Adopted source traceability, durable retry behavior, and deterministic assertions before model evaluation. The synthetic scenario supplies repeatable examples for later evidence and proposal evaluation. [The Substack Brain](https://github.com/neural-maze/substack-brain-course)

### Local security and observability

The demo binds to loopback. Operator IDs are supplied by the local caller and are only checked against the synthetic directory and assignment rules. Structured logs include request ID, route, status, and latency. Report contents and credentials stay out of logs.

WSL Git is configured with the plaintext `store` credential helper. The secure replacement is Git Credential Manager from Git for Windows, called from WSL, with storage in Windows Credential Manager. Migrating requires the repository owner to sign in through the GitHub browser flow and verify access. [Microsoft WSL Git guide](https://learn.microsoft.com/en-us/windows/wsl/tutorials/wsl-git)

## Phase 2 wearable integration

The companion WebView uses a typed fetch client with a six-second deadline, runtime response checks, and structured conflicts. Vite forwards local requests through a same-origin development proxy. The renderer uses one 576 × 288 SDK text container. The controller serializes each input and display update, ignores rapid repeated taps, and lays out short screens for triage, evidence, review, preview, explicit confirmation, and receipts. Pending findings sort by severity, then age and ID for stable ordering. Evidence is displayed after its source ID, source reference, and text match the stored report.

A handover preview shows versioned eligible and outstanding items. The synthetic scenario uses its configured outgoing actor to request the preview on behalf of the outgoing shift. The incoming operator selects an explicit acceptance option from a confirmation screen that opens on Cancel. Before issuing acceptance, the WebView journals the handover ID, version, actor ID, and operation UUID. It reuses that command for ambiguous outcomes, including after a WebView reload when its local storage survives. A stale preview requires a fresh preview and confirmation. Relay shows success after the server's persisted receipt is fetched and matched to the handover and shift. The durable source of record is SQLite.

The simulator flow has been exercised with a real FastAPI server, including a stale preview, duplicate rejection, and recovery after stopping and restarting the backend. The simulator uses one synthetic operator context in one WebView. Receipt pointers are local to that origin, and recovery across devices or cleared storage would need a server-side receipt lookup tied to an authenticated actor. The paired phone WebView requires its own reachable API and network permissions. Physical G2 behavior and physical installation remain unverified.

## Phase 3 evidence-grounded proposals

A provider-independent analyzer runs `extract-v1` and `semantic-review-v1` in sequence. The system instructions and report data use separate message fields. Gemini receives a simplified structured response schema and Relay validates the full Pydantic contracts afterward. The adapter bounds provider calls and retries. The workflow holds the SQLite write transaction only while storing execution metadata and pending proposals.

Relay validates report scope, exact excerpts, asset and action relationships, and the human-review action vocabulary before persistence. Duplicate semantic proposals and matching deterministic findings with the same cited report set are suppressed. Passing those checks establishes provenance. A human reviewer decides whether the evidence justifies the semantic conclusion. The model has no tools or authority to update actions, accept a handover, or write a receipt. A human acknowledgment changes review status through the existing API and preserves the AI provenance.

The official simulator verified the live FD-22 proposal, both original excerpts, human acknowledgment, deterministic transfer with Gemini unconfigured, and receipt retrieval after restarting the backend. The first evaluation exposed false positives on ambiguous and compatible language even with exact evidence. Keep abstention and human review as system requirements. See the [backend evaluation instructions](../backend/README.md).
