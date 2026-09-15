#!/usr/bin/env bash
# Start the nanoCAS backend and the frontend dev server from a checkout.
#
#   ./start_nanocas.sh            # backend on :5007, frontend on :3000
#   BACKEND_PORT=8000 ./start_nanocas.sh
#
# Requirements: python3 (>=3.10) with server/requirements.txt installed
# (a ./venv is activated automatically if present), node/npm, and
# minimap2 + samtools on PATH. Logs go to ./logs/.
set -euo pipefail

NANOCAS_PATH="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STAMP="$(date +'%Y%m%d_%H%M%S')"
mkdir -p "${NANOCAS_PATH}/logs"

if [ -f "${NANOCAS_PATH}/venv/bin/activate" ]; then
  # shellcheck disable=SC1091
  source "${NANOCAS_PATH}/venv/bin/activate"
fi

for tool in python3 npm minimap2 samtools; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    echo "ERROR: '$tool' is not on PATH. See README.md > Installation." >&2
    exit 1
  fi
done

export BACKEND_PORT="${BACKEND_PORT:-5007}"
export PORT="${FRONTEND_PORT:-3000}"

echo "Starting backend on :${BACKEND_PORT} (log: logs/backend_${STAMP}.log)"
( cd "${NANOCAS_PATH}/server" && python3 nanocas.py ) > "${NANOCAS_PATH}/logs/backend_${STAMP}.log" 2>&1 &
BACKEND_PID=$!

if [ ! -d "${NANOCAS_PATH}/frontend/node_modules" ]; then
  echo "Installing frontend dependencies (first run)…"
  ( cd "${NANOCAS_PATH}/frontend" && npm ci --no-audit --no-fund ) > "${NANOCAS_PATH}/logs/npm_${STAMP}.log" 2>&1
fi

echo "Starting frontend on :${PORT} (log: logs/frontend_${STAMP}.log)"
( cd "${NANOCAS_PATH}/frontend" && BROWSER=none npm start ) > "${NANOCAS_PATH}/logs/frontend_${STAMP}.log" 2>&1 &
FRONTEND_PID=$!

trap 'echo "Stopping…"; kill ${BACKEND_PID} ${FRONTEND_PID} 2>/dev/null || true' INT TERM EXIT
echo "nanoCAS is starting: http://localhost:${PORT}  (API http://localhost:${BACKEND_PORT})"
wait
