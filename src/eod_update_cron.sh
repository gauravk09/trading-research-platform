#!/bin/bash
# eod_update_cron.sh — wrapper script called by cron at 10 PM daily
#
# Cron has a minimal environment — this script sets up PATH and activates
# conda so Python and all packages are available.

PROJECT="$HOME/Tading Setup"
PYTHON="$HOME/anaconda3/bin/python"
LOG="$PROJECT/logs/eod_cron_$(date +%Y%m%d).log"

echo "=== EOD Update started at $(date) ===" >> "$LOG"

# Run the full EOD update
cd "$PROJECT" && "$PYTHON" src/eod_update.py >> "$LOG" 2>&1

EXIT_CODE=$?
echo "=== Finished at $(date) — exit code $EXIT_CODE ===" >> "$LOG"

if [ $EXIT_CODE -ne 0 ]; then
    echo "ERROR: EOD update failed — check log at $LOG" >> "$LOG"
    osascript -e "display notification \"EOD update failed — Kite token likely expired. Run: python src/auth.py\" with title \"Trading Setup\" sound name \"Basso\""
    exit $EXIT_CODE
fi

# The web dashboard (webapp/) needs no restart: its API caches are keyed on
# file mtime, so fresh parquet files are picked up on the next request.

# Print last 10 lines to stdout (captured by cron for email)
tail -10 "$LOG"
