#!/bin/bash
# install_daily_briefing_cron.sh
# Installs the daily briefing cron job.

set -euo pipefail

# ===== CONFIGURATION =====
# PROJECT_ROOT auto-detects from this script's location. Edit CRON_SCHEDULE to
# change when the briefing runs (cron syntax). The wrapper picks its own Python.
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CRON_SCHEDULE="0 6 * * *"  # Daily at 6 AM
# =========================

WRAPPER="$PROJECT_ROOT/run_daily_briefing_cron.sh"

if [[ ! -f "$WRAPPER" ]]; then
    echo "Error: $WRAPPER not found. Run this from the project root."
    exit 1
fi

# Make wrapper executable
chmod +x "$WRAPPER"

# Build cron entry
CRON_ENTRY="$CRON_SCHEDULE $WRAPPER"

# Check if already installed
if crontab -l 2>/dev/null | grep -q "$WRAPPER"; then
    echo "Cron job already installed:"
    crontab -l | grep "$WRAPPER"
    exit 0
fi

# Install
(crontab -l 2>/dev/null; echo "$CRON_ENTRY") | crontab -
echo "Installed cron job:"
crontab -l | grep "$WRAPPER"
echo ""
echo "To remove: crontab -e (delete the line) or: crontab -l | grep -v \"$WRAPPER\" | crontab -"