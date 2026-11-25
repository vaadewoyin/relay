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
