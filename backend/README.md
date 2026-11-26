# Relay backend

This Python 3.12 service runs a deterministic facilities handover against SQLite.

## Run the synthetic demonstration

From `backend/`, install dependencies and seed a disposable database.

```bash
uv sync --locked
export RELAY_DB_PATH="$(mktemp -d)/relay.sqlite3"
uv run --locked python -m relay.demo seed
uv run --locked python -m relay.api
```

Leave the service running and use another terminal from `backend/`.

```bash
uv run --locked python -m relay.demo run
```

The runner sends real HTTP requests. It ingests three synthetic reports about a loading-dock sump pump, verifies all six finding types and their source evidence, records a review, and demonstrates stale rejection and idempotent retries. The incoming operator accepts the unresolved pump repair. The unassigned bypass inspection stays with the outgoing shift and appears in the stored receipt. Use a fresh database to replay the scenario from its initial state.

Open [Swagger UI](http://127.0.0.1:8000/docs) or the [OpenAPI schema](http://127.0.0.1:8000/openapi.json). The service uses `RELAY_DB_PATH` for its SQLite file (default `relay.sqlite3`), `RELAY_PORT` for its loopback port (default `8000`), and `RELAY_LOG_LEVEL` for its log level (default `INFO`). Use `--url` with the demo runner if you change the port.

## Command behavior

- Send a fresh UUID as `operation_id` for each new mutation. Retrying a committed command with the same operation ID, route, and payload returns the original response. Reusing the key with a different route or payload returns HTTP 409. After a failed command, use a new UUID when revising its inputs.
- Read the current action version before changing its status. A stale write returns HTTP 409 and records an evidence-backed finding. If work changes after a handover preview, create and review a new preview.
- Preview as the outgoing operator and accept as the assigned incoming operator with `confirmed: true` and the preview's version. Only unresolved work currently owned by the outgoing operator can transfer. The receipt records the work transferred and the work left outstanding.
- The request ID in an error response matches the `X-Request-ID` response header and the structured request log.

## Checks

```bash
uv run --locked ruff check
uv run --locked ruff format --check
uv run --locked pytest
```

## Trust boundary

This API is for trusted local clients and synthetic data. The supplied operator IDs exercise business authorization rules. Any caller who can reach the API can claim an operator ID. Before a shared deployment, bind actors to authenticated identities, restrict record access, and define protection and retention for the SQLite files, including their WAL. The standard runner binds only to `127.0.0.1`. Request logs omit report text and payloads.

## Live Gemini handover analysis

Use a disposable database and the same frontend and simulator launch commands from the [wearable walkthrough](../frontend/README.md). From `backend/`, replace the fixture and backend launch steps with:

```bash
mkdir -p ../artifacts
export RELAY_DB_PATH="$(mktemp -d)/relay.sqlite3"
uv run --locked python -m relay.demo prepare-intelligence > ../artifacts/wearable-context.json
uv run --locked --env-file .env python -m relay.api
```

Set `GEMINI_API_KEY` in the ignored `backend/.env` or in the server's environment. Keep it out of shell history and Git. Generate a key in [Google AI Studio](https://aistudio.google.com/apikey).

In Swagger UI, call `POST /ai/analyses` with `shift_id` set to the fixture's `outgoingShiftId` and a fresh UUID as `operation_id`. The response contains the persisted execution metadata, failure category if applicable, and accepted proposal IDs. Retrieve it again at `GET /ai/analyses/{execution_id}`. Retrying the same operation ID returns the stored result. Use a new ID for a deliberate rerun.

Refresh the wearable brief after the analysis. Open the **AI HIGH Conflicting reports** item, scroll through both source excerpts, then return to the proposal to acknowledge or reject it. Continue with the existing explicit handover confirmation and receipt. Restarting the backend without a key and submitting a new analysis returns `not_configured`. Existing findings, human review, and deterministic handover remain available.

The default model is `gemini-3.1-flash-lite` with the official `google-genai` SDK. Configure `RELAY_GEMINI_MODEL`, `RELAY_AI_SECONDS` (35 seconds total), `RELAY_AI_REPORTS` (12 reports), `RELAY_AI_INPUT_BYTES` (32,000 bytes per stage), `RELAY_AI_OUTPUT_TOKENS` (2,600 tokens per stage), and `RELAY_AI_ATTEMPTS` (2 attempts per stage, maximum 3). A run sends two structured requests when both stages complete. The loopback demo analyzes only reports labeled synthetic by default. Enabling `RELAY_AI_ALLOW_OPERATIONAL_DATA=1` sends eligible operational report text to Gemini. Use of real reports requires appropriate authorization and data handling. [Gemini model and capabilities](https://ai.google.dev/gemini-api/docs/models/gemini-3.1-flash-lite)

### Evaluate

```bash
uv run --locked python -m relay.intelligence.evaluate \
  --output ../artifacts/phase3/evaluation-validator.json
uv run --locked --env-file .env python -m relay.intelligence.evaluate \
  --live --limit 22 --pause 2 --output ../artifacts/phase3/evaluation-live.json
```

The suite contains 11 positive cases, 11 negative cases, and two deterministic invalid-evidence exercises. A match requires the expected finding type and evidence that includes the labeled excerpts from the correct reports. The scorer reports transport failures separately from semantic quality, and uses observed text tokens and published standard rates for a cost estimate. Actual billing depends on the account, and usage missing from responses is excluded. The live runner stops on credential, quota, or request failures. [Gemini API pricing](https://ai.google.dev/gemini-api/docs/pricing)

The first full live run completed 22/22 cases on `gemini-3.1-flash-lite` with `extract-v1` and `semantic-review-v1`. Precision was 10/13, recall 10/11, and false-positive rate 2/11. Schema and emitted-proposal citation validity were 100%. Nine of 11 negative cases abstained. Both injected-report cases abstained, and the two deterministic invalid-citation exercises passed. Median latency was 5.782 seconds. Reported usage was 34,943 input and 12,448 output tokens, for an estimated standard cost of $0.02741. The model over-inferred contradictions in an ambiguous-reference case and a compatible ownership handoff. One predicted the correct ownership finding type but missed the labeled evidence anchor under the strict scorer.
