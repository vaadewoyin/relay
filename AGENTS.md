# Relay Git development policy

- Inspect working tree status and diffs before staging. Stage reviewed paths explicitly and preserve user-authored work and existing history.
- Commit individual logical engineering tasks using scoped Conventional Commits such as `feat(wearable): add finding review`. Use separate commits for independently reviewable features, fixes, tests, infrastructure, and documentation where that keeps each commit usable. Keep tests with their implementation when splitting would leave an intermediate commit broken or unverified.
- Run relevant checks before committing. Let the work determine the number of commits. Preserve meaningful task boundaries and never manufacture commits for contribution counts.
- Keep credentials, secrets, `.env` files, `node_modules`, and unnecessary generated artifacts out of Git. Review staged contents before committing.
- Push verified commits regularly to the intended GitHub repository. Compare the local commit with the remote branch after pushing and report a successful push only after verification.
- Keep the repository synchronized with GitHub and the working tree clean after each milestone where practical. Obtain explicit user approval before force-pushing, rewriting published history, or discarding existing work.

Follow [frontend/AGENTS.md](frontend/AGENTS.md) for frontend engineering. Phase 1 requires review of the Phase 0 simulator results or explicit authorization of an alternative plan.

## Backend engineering

- Use Python 3.12 and the backend's committed uv lockfile. Run `uv run --locked ruff check`, `uv run --locked ruff format --check`, and `uv run --locked pytest` from `backend/`. Run the existing frontend checks when changing shared contracts or simulator behavior.
- Keep Pydantic contracts and deterministic rules independent of HTTP, SQLite, and external providers. Put command orchestration in the application service and keep authorization, stale checks, and operation deduplication inside the same transaction as the write.
- Preserve immutable source text and check evidence against the original report. Treat integrity findings as proposals for human review. An incoming operator's explicit acceptance authorizes the transfer.
- Keep synthetic fixtures reproducible. Cover observed failures with deterministic assertions before adding model-based evaluation. Log structured operational metadata without source text, credentials, or request bodies.
- Keep the demonstration service on loopback with synthetic data. Review the deterministic Phase 1 workflow independently before introducing external AI or synchronization.

- Version extraction and proposal prompts whenever their instructions change. Keep report data in an untrusted channel and expose no operational tools to the model.
- Ground model output against stored evidence before persisting pending proposals. Keep proposal review and responsibility transfer under the existing human-authorized commands.
- For AI work, run the deterministic validator suite before an opt-in live evaluation. Record prompt and dataset versions, semantic metrics, failures, latency, and observed token usage. Keep request content and credentials out of logs.
