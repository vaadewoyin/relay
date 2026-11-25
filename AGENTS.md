# Relay Git development policy

- Inspect working tree status and diffs before staging. Stage reviewed paths explicitly and preserve user-authored work and existing history.
- Keep changes small and reviewable. Run relevant tests before committing completed milestones as meaningful, atomic Conventional Commits, using types such as `feat`, `fix`, `test`, `docs`, `refactor`, `chore`, and `ci`. Avoid commits made solely to increase contribution counts.
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
