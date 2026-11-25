# Relay

Nothing gets lost between shifts.

Relay is a wearable shift-handover system for facilities and hospitality maintenance teams using Even G2. Phase 0 is a TypeScript and Vite smoke app built on the official [Even Hub minimal starter](https://github.com/even-realities/evenhub-templates/tree/8cb01354f5ee914c5fab97d06e6d13b28eeb5815/minimal). See [DESIGN.md](DESIGN.md) and the [implementation checklist](CHECKLIST.md).

## Run locally

Use Node.js 22.12 or later in the 22.x line and npm. The lockfile installs the official SDK, CLI and simulator locally.

```bash
npm ci
npm run dev -- --host 127.0.0.1 --strictPort
```

Run the simulator in another terminal. On Ubuntu 24.04 under WSL2, a working WSLg session and WebKitGTK 4.1 runtime are required. If launch reports a missing `libwebkit2gtk-4.1.so.0`, install `libwebkit2gtk-4.1-0` with apt and retry.

```bash
npm run simulate -- --automation-port 9898
```

The glasses view should show **Hello, Relay**. Click once to display **Taps: 1**, send up and down to verify the count stays at one, then double-click to open the exit flow. The simulator automation API exposes `GET /api/ping`, `GET /api/screenshot/glasses` and `POST /api/input` on `http://127.0.0.1:9898`. Input actions are `click`, `up`, `down` and `double_click`.

## Check and package

```bash
npm test
npm run build
npm run pack
```

The Node smoke test runs the real app entry point with a mocked SDK bridge. The package command produces `out.ehpk`. Keep `--sdk-ver` and `app.json` aligned with the SDK version in the lockfile so the packer derives the correct minimum companion app version.

## Official development skills

[Everything EvenHub](https://github.com/even-realities/everything-evenhub) includes the template, SDK reference, input handling, device features and simulator automation guidance. Install it with Codex CLI and restart Codex to load the skills.

```bash
codex plugin marketplace add even-realities/everything-evenhub
codex plugin add everything-evenhub@everything-evenhub
```
