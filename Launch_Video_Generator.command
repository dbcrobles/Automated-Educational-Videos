#!/bin/bash
# ── Video Generator — one launcher for everything ────────────────────────────
# Starts the backend orchestrator + the Reflex dashboard, waits for the
# dashboard to come up, then opens it in the browser. Closing this window
# (or Ctrl-C) shuts both down.
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$DIR"

echo "🎬 Video Generator — starting…"

# Activate the project virtualenv (python -m works even with spaces in the path)
if [ -d ".venv" ]; then
    source .venv/bin/activate
fi

# Stop any previous instances to avoid port/lock conflicts
pkill -f "reflex run" 2>/dev/null || true
if [ -f "Backend/orchestrator.lock" ]; then
    kill "$(cat Backend/orchestrator.lock)" 2>/dev/null || true
fi
sleep 1

# Start the backend orchestrator (unbuffered so the log is live)
echo "▶ Backend orchestrator…      log: Backend/orchestrator.log"
( cd Backend && python3 -u main.py >> orchestrator.log 2>&1 ) &
BACKEND_PID=$!

# Open the browser once the dashboard actually responds
( for _ in $(seq 1 60); do
      if curl -s -o /dev/null http://localhost:3000; then
          open http://localhost:3000
          exit 0
      fi
      sleep 2
  done
  echo "⚠️  Dashboard didn't come up after 2 minutes — check Frontend/dashboard.log" ) &

# Run the dashboard in the foreground so this window controls the session
echo "▶ Dashboard on http://localhost:3000 …   log: Frontend/dashboard.log"
cd Frontend
python -m reflex run 2>&1 | tee dashboard.log

# Dashboard exited → stop the backend too
kill "$BACKEND_PID" 2>/dev/null || true
echo "Pipeline shut down."