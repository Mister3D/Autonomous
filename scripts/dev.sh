#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

export AUTONOMOUS_HOME="${AUTONOMOUS_HOME:-$ROOT/data}"

if [[ ! -f "$AUTONOMOUS_HOME/password.hash" ]]; then
  echo "Run: autonomous init --password '…' first"
  exit 1
fi

autonomous serve --host 127.0.0.1 --port 8787 --dev &
API_PID=$!
trap 'kill $API_PID 2>/dev/null || true' EXIT

cd "$ROOT/frontend"
npm run dev -- --host 127.0.0.1 --port 5173
