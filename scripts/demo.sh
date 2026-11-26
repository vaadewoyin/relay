#!/usr/bin/env bash
set -euo pipefail

mode=${1:-offline}
case "$mode" in
  offline|live) ;;
  *) printf 'Usage: bash scripts/demo.sh [offline|live]\n' >&2; exit 2 ;;
esac

repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
cd "$repo/backend"
uv sync --locked
run=(uv run --locked)
if [[ $mode == live ]]; then
  [[ -f .env ]] || { printf 'Live mode requires backend/.env. See backend/README.md.\n' >&2; exit 2; }
  run+=(--env-file .env)
  "${run[@]}" python - <<'PY'
import os
from relay.notion.client import Sources

try:
    Sources.from_environment()
    assert os.getenv("NOTION_TOKEN")
    assert os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
except (KeyError, ValueError, AssertionError):
    raise SystemExit("Live configuration is incomplete. Check the token and data-source variables.")
PY
fi

export RELAY_PORT=${RELAY_PORT:-8000}
demo_dir=$(mktemp -d "${TMPDIR:-/tmp}/relay-demo.XXXXXX")
export RELAY_DB_PATH="$demo_dir/relay.sqlite3"
if [[ $mode == live ]]; then
  "${run[@]}" python -m relay.notion.demo seed > "$demo_dir/context.json"
else
  "${run[@]}" python -m relay.demo prepare-wearable > "$demo_dir/context.json"
fi

printf 'Run directory (kept on exit): %s\n' "$demo_dir"
printf 'Frontend terminal:\n  cd %q && npm ci\n' "$repo/frontend"
printf '  RELAY_PROXY_TARGET=http://127.0.0.1:%s VITE_RELAY_CONTEXT="$(cat %q)" npm run dev -- --strictPort\n' "$RELAY_PORT" "$demo_dir/context.json"
printf 'Simulator terminal:\n  cd %q && npm run simulate -- --automation-port 9898\n' "$repo/frontend"
if [[ $mode == live ]]; then
  printf 'Open http://127.0.0.1:%s/docs. Verify Notion, import, analyze, and publish as described in backend/README.md.\n' "$RELAY_PORT"
fi
exec "${run[@]}" python -m relay.api
