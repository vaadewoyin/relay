# Relay engineering

- AI proposes findings and updates. Deterministic code validates them. Humans authorize changes.
- Consult official SDK and API documentation before implementing integrations. Use Everything EvenHub for glasses UI, input routing, CLI and simulator work.
- Keep credentials server-side and out of version control, frontend bundles, test fixtures and logs.
- Prefer one complete handover workflow. Keep the frontend on TypeScript, Vite and the official Even Hub SDK. Use Python 3.12, FastAPI, Pydantic and SQLite for backend work after Phase 0 passes.
- Test each increment. Run `npm test` and `npm run build` for frontend changes and Pytest for backend changes once available.
- Record the difference between bridge-mock tests, official simulator results and physical device verification.
- See [DESIGN.md](DESIGN.md) and [CHECKLIST.md](CHECKLIST.md) for the design and implementation order.
