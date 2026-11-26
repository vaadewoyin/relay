# Implementation checklist

Submission is due November 29, 2026 at 20:59 WAT. Budget is $10 and approximately 20–25 development hours.

## P0 · Phase 0 accepted

- [x] Inspect the environment, compare the starter with upstream and install Everything EvenHub.
- [x] Install dependencies, brand the starter and pass the bridge smoke test, type check and build.
- [x] Capture the initial greeting in the official simulator. Verify single tap increments and scrolling in either direction preserves the count.
- [x] Verify double tap delivers the exit gesture and clears the simulator glasses display.
- [x] Accept Phase 0 with documented limitations. The SDK exit confirmation dialog, physical G2 behavior and physical package installation remain unverified.

## P0 · End-to-end vertical slice after Phase 0 passes

- [x] Build a deterministic FastAPI and SQLite flow for report intake, basic findings, evidence and review.
- [x] Add explicit acceptance, transactional receipts, version checks and idempotent retries. Cover stale state and duplicate actions with Pytest.
- [x] Independently review and accept the deterministic Phase 1 workflow.
- [x] Connect the wearable queue, source evidence and confirmation screens to the API. Verify the seeded shift, persistent receipt, stale preview and offline recovery in the official simulator.
- [x] Accept the Phase 2 wearable flow and rerun the full Phase 2 verification.
- [x] Generate structured Gemini proposals, validate source evidence, and record human review in the simulator. Verify deterministic fallback.
- [ ] Independently review Phase 3 and its live evaluation before starting further integrations.
- [ ] Verify real Notion import and write-back against a test data source. Exercise the sync outage and retry path.
- [ ] Run frontend and backend checks in GitHub Actions. Record the simulator workflow and prepare submission materials.

## P1 · After the core demo works

- [ ] Add voice capture, structured action preview and explicit confirmation. Verify the simulator microphone path and manual fallback.
