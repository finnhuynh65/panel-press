#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
PORT="${PORT:-8080}"

cd "$REPO_DIR"

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "Python executable not found: $PYTHON_BIN" >&2
  echo "Set PYTHON_BIN to a valid Python command, for example: PYTHON_BIN=python3 ./start.sh" >&2
  exit 1
fi

if command -v lsof >/dev/null 2>&1; then
  LISTENING_PIDS="$(lsof -tiTCP:"$PORT" -sTCP:LISTEN || true)"
  if [[ -n "$LISTENING_PIDS" ]]; then
    CURRENT_UID="$(id -u)"
    STOPPED_ANY=0
    for PID in $LISTENING_PIDS; do
      OWNER_UID="$(ps -o uid= -p "$PID" 2>/dev/null | tr -d ' ' || true)"
      if [[ "$OWNER_UID" == "$CURRENT_UID" ]]; then
        echo "Stopping existing process $PID on port $PORT..."
        kill "$PID" 2>/dev/null || true
        STOPPED_ANY=1
      else
        echo "Port $PORT is owned by another user/process; cannot stop PID $PID." >&2
      fi
    done
    if [[ "$STOPPED_ANY" == "1" ]]; then
      for _ in 1 2 3 4 5; do
        sleep 0.2
        lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1 || break
      done
    fi
    if lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
      echo "Port $PORT is still in use." >&2
      echo "Use another port: PORT=8081 ./start.sh" >&2
      exit 1
    fi
  fi
fi

echo "Starting Panel Press at http://127.0.0.1:$PORT/"
exec env PORT="$PORT" "$PYTHON_BIN" webapp.py
