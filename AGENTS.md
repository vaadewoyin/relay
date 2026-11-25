# Relay Git development policy

- Inspect working tree status and diffs before staging. Stage reviewed paths explicitly and preserve user-authored work and existing history.
- Keep changes small and reviewable. Run relevant tests before committing completed milestones as meaningful, atomic Conventional Commits, using types such as `feat`, `fix`, `test`, `docs`, `refactor`, `chore`, and `ci`. Avoid commits made solely to increase contribution counts.
- Keep credentials, secrets, `.env` files, `node_modules`, and unnecessary generated artifacts out of Git. Review staged contents before committing.
- Push verified commits regularly to the intended GitHub repository. Compare the local commit with the remote branch after pushing and report a successful push only after verification.
- Keep the repository synchronized with GitHub and the working tree clean after each milestone where practical. Obtain explicit user approval before force-pushing, rewriting published history, or discarding existing work.

Follow [frontend/AGENTS.md](frontend/AGENTS.md) for frontend engineering. Phase 1 requires review of the Phase 0 simulator results or explicit authorization of an alternative plan.
