# Implementation checklist

Submission is due November 29, 2026 at 20:59 WAT. Budget is $10 and approximately 20–25 development hours.

## P0 · Phase 0 gate

- [x] Inspect the environment, compare the starter with upstream and install Everything EvenHub.
- [x] Install dependencies, brand the starter and pass the bridge smoke test, type check and build.
- [x] Capture the initial greeting in the official simulator. Verify single tap increments and scrolling in either direction preserves the count.
- [x] Verify double tap delivers the exit gesture and clears the simulator glasses display.
- [ ] Verify the SDK exit confirmation dialog in the simulator UI or on physical G2 glasses. The simulator automation capture showed a cleared framebuffer after double tap.

## P0 · End-to-end vertical slice after Phase 0 passes

- [ ] Build a deterministic FastAPI and SQLite flow for report intake, basic findings, evidence and review.
- [ ] Add explicit acceptance, transactional receipts, version checks and idempotent retries. Cover stale state and duplicate actions with Pytest.
- [ ] Connect the wearable queue, source evidence and confirmation screens to the API. Walk through a seeded shift in the simulator.
- [ ] Verify real Notion import and write-back against a test data source. Exercise the sync outage and retry path.
- [ ] Add Gemini structured proposals and evidence validation. Demonstrate the deterministic fallback.
- [ ] Run frontend and backend checks in GitHub Actions. Record the simulator workflow and prepare submission materials.

## P1 · After the core demo works

- [ ] Add voice capture, structured action preview and explicit confirmation. Verify the simulator microphone path and manual fallback.
