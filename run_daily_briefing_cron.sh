#!/bin/bash
set -euo pipefail

# ===== CONFIGURATION =====
# REPO auto-detects from this script's location, so no editing is needed when
# the repo is cloned to a new path. PYTHON defaults to the uv-managed venv
# (created by `uv sync`); override PYTHON if you use conda/another interpreter.
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="${PYTHON:-$REPO/.venv/bin/python}"
LOG_DIR="$REPO/logs"
LOG_FILE="$LOG_DIR/cron.log"
LOCK_DIR="$REPO/cache/run_daily_briefing.lock"
LOCK_PID_FILE="$LOCK_DIR/pid"
LOCK_TIME_FILE="$LOCK_DIR/started_at"
# =======================================================

timestamp() {
  date '+%Y-%m-%d %H:%M:%S'
}

log() {
  printf '[%s] %s\n' "$(timestamp)" "$1" >> "$LOG_FILE"
}

cleanup_lock() {
  rm -f "$LOCK_PID_FILE" "$LOCK_TIME_FILE"
  rmdir "$LOCK_DIR" 2>/dev/null || true
}

mkdir -p "$LOG_DIR" "$REPO/cache"

if [[ ! -x "$PYTHON" ]]; then
  log "Python interpreter is not executable: $PYTHON"
  exit 1
fi

if mkdir "$LOCK_DIR" 2>/dev/null; then
  printf '%s\n' "$$" > "$LOCK_PID_FILE"
  printf '%s\n' "$(timestamp)" > "$LOCK_TIME_FILE"
  trap cleanup_lock EXIT INT TERM
else
  existing_pid=""
  if [[ -f "$LOCK_PID_FILE" ]]; then
    existing_pid="$(cat "$LOCK_PID_FILE")"
  fi

  if [[ -n "$existing_pid" ]] && kill -0 "$existing_pid" 2>/dev/null; then
    log "Another daily briefing run is already active with PID $existing_pid; skipping."
    exit 0
  fi

  log "Removing stale lock from prior run${existing_pid:+ (PID $existing_pid)}."
  rm -f "$LOCK_PID_FILE" "$LOCK_TIME_FILE"
  rmdir "$LOCK_DIR" 2>/dev/null || true

  if ! mkdir "$LOCK_DIR" 2>/dev/null; then
    log "Failed to acquire lock at $LOCK_DIR"
    exit 1
  fi

  printf '%s\n' "$$" > "$LOCK_PID_FILE"
  printf '%s\n' "$(timestamp)" > "$LOCK_TIME_FILE"
  trap cleanup_lock EXIT INT TERM
fi

log "Starting daily briefing run."

cd "$REPO"
"$PYTHON" scripts/run_daily_briefing.py \
  --config config/daily_ap.yaml \
  --phase full \
  --send >> "$LOG_FILE" 2>&1

log "Finished daily briefing run successfully."