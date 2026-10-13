#!/usr/bin/env bash
# Start the KrishiSaathi API (port 8000) and frontend (port 8080) for local development.
# First run creates backend/.venv and installs dependencies automatically.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

PYTHON="${PYTHON:-python3}"
if ! command -v "$PYTHON" >/dev/null 2>&1; then echo "Python 3.10+ is required (python3 not found)."; exit 1; fi
if ! command -v npm >/dev/null 2>&1; then echo "Node.js 18+ is required (npm not found)."; exit 1; fi

if [ ! -x "$ROOT/backend/.venv/bin/python" ]; then
  echo "Creating backend virtual environment..."
  "$PYTHON" -m venv "$ROOT/backend/.venv"
  "$ROOT/backend/.venv/bin/python" -m pip install --upgrade pip >/dev/null
  "$ROOT/backend/.venv/bin/python" -m pip install -r "$ROOT/backend/requirements.txt"
fi
if [ ! -d "$ROOT/Frontend/node_modules" ]; then
  echo "Installing frontend dependencies..."
  (cd "$ROOT/Frontend" && npm install)
fi

cleanup() { trap - INT TERM EXIT; kill 0 2>/dev/null || true; }
trap cleanup INT TERM EXIT

(cd "$ROOT/backend" && exec .venv/bin/python -m uvicorn main:app --reload --port 8000) &
(cd "$ROOT/Frontend" && exec npm run dev) &

echo "API:      http://127.0.0.1:8000/docs"
echo "Frontend: http://localhost:8080"
wait
