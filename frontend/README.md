# Relay

Nothing gets lost between shifts.

Relay is a wearable shift-handover system for facilities and hospitality maintenance teams using Even G2. Follow the [design](DESIGN.md) and [implementation checklist](CHECKLIST.md).

## Run the synthetic simulator demo

Use Python 3.12, uv, Node.js 22.12 or later in the 22.x line, and npm. On WSL2, the official Linux simulator needs WSLg and WebKitGTK 4.1. On Ubuntu, the runtime package is `libwebkit2gtk-4.1-0`.

From `backend/`:

```bash
uv sync --locked
mkdir -p ../artifacts
export RELAY_DB_PATH="$(mktemp -d)/relay.sqlite3"
uv run --locked python -m relay.demo prepare-wearable > ../artifacts/wearable-context.json
uv run --locked python -m relay.api
```

The fixture creates the directory and reports while leaving review and acceptance pending. Keep the backend running. From `frontend/` in a second terminal:

```bash
npm ci
VITE_RELAY_CONTEXT="$(cat ../artifacts/wearable-context.json)" npm run dev -- --strictPort
```

Launch the simulator from `frontend/` in a third terminal:

```bash
npm run simulate -- --automation-port 9898
```

The default Vite proxy forwards `/relay-api` to FastAPI at `http://127.0.0.1:8000`. For a different backend port, set `RELAY_PROXY_TARGET` when starting Vite. When using a different Vite port, pass its URL to the simulator directly. The shift context contains synthetic IDs and display labels that can be read in the frontend bundle.

### Walkthrough

1. From **Shift brief**, tap **Finding queue**, then tap the first high-severity **Overdue action**. Tap **Source evidence** to read the original report.
2. Double tap to return to the finding. Scroll to **Review finding**, tap to open it, then scroll to **Acknowledge finding** and tap to record it.
3. Double tap twice to return to the brief. Scroll to **Handover**, tap, and scroll through eligible and outstanding work.
4. Tap the preview to open **Confirm transfer**. The selection starts at **Cancel**. Scroll to **Accept responsibility**, then tap. Relay displays the receipt after fetching it back from FastAPI.
5. Scroll the receipt to see outstanding work. Return to the brief and choose **Handover receipt** to fetch it again. You can also inspect the ID at `GET /handover-receipts/{receipt_id}` in [Swagger UI](http://127.0.0.1:8000/docs).

Scroll moves the selection or page. Single tap activates the selection. Double tap goes back, or requests SDK exit from the brief. On a stale preview, retry opens a fresh preview and requires a fresh confirmation. After a connection failure, tap **Retry** once the server returns. If a previous disposable database has left a saved receipt pointer, opening that unavailable receipt offers recovery. A different Vite origin also isolates the simulator's local transfer state.

The simulator automation API exposes `GET /api/ping`, `GET /api/screenshot/glasses`, and `POST /api/input` at `http://127.0.0.1:9898`. The input actions are `click`, `up`, `down`, and `double_click`. Save the screenshot endpoint as a PNG and view it against a dark background to see the transparent framebuffer.

## Simulator and physical networking

In the simulator, the companion WebView opens Vite and uses its same-origin development proxy. The FastAPI server can stay bound to loopback. In a packaged app, the paired phone hosts the WebView and its loopback refers to the phone. A physical deployment needs a phone-reachable HTTPS API configured through `VITE_RELAY_API_BASE`, an appropriate Even Hub network allowlist in `app.json`, and API CORS settings for the actual companion WebView origin. The current package has no deployment URL or network allowlist. Treat it as a packaging check. The local demo trusts actor IDs from its synthetic context and must stay on trusted loopback. A shared deployment needs authenticated actors and per-record access controls.

## Checks and packaging

```bash
npm test
npm run build
npm run pack
```

The tests cover the API client, navigation and transfer recovery. The SDK entry test uses a mocked bridge. Packaging produces `out.ehpk` with relative asset URLs. Keep `--sdk-ver` and `app.json` aligned with the SDK version in the lockfile so the packer derives the correct companion app minimum.

## Official development skills

[Everything EvenHub](https://github.com/even-realities/everything-evenhub) includes the template, SDK reference, input handling, device features and simulator automation guidance. Install it with Codex CLI and restart Codex to load the skills.

```bash
codex plugin marketplace add even-realities/everything-evenhub
codex plugin add everything-evenhub@everything-evenhub
```
