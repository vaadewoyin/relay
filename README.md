# Relay

Relay is a shift handover app for Even G2. It pulls facilities reports from Notion, checks them with deterministic rules and optional Gemini analysis, and shows source-backed findings in the wearable. A human reviews a proposal and explicitly accepts responsibility. SQLite commits the transfer and receipt locally, then authorized outcomes can sync back to Notion.

## Run the demo

Install Python 3.12, uv, Node.js 22, npm, and the [Even Hub simulator](frontend/README.md). From the repository root:

```bash
bash scripts/demo.sh offline
```

Follow the printed Vite and simulator commands. The deterministic mode uses synthetic reports and an isolated SQLite database. For the live Notion and Gemini workflow, follow the [workspace setup](backend/README.md) and run `bash scripts/demo.sh live`. Keep the API on loopback and use a dedicated synthetic workspace.

See the [architecture](frontend/DESIGN.md), [evaluation history](backend/evals/results-v2.md), and [submission checklist](SUBMISSION.md).
