#!/bin/zsh
# Run the full EOD data update by hand (same job the 8 PM cron runs).
# Double-click this file in Finder, or run it from a terminal.
# Safe during market hours: prices are fetched only up to the last completed
# session, so a midday run backfills missed days without today's partial candle.

cd "$(dirname "$0")/../.." || exit 1

echo "Updating data... (full log in logs/eod_cron_$(date +%Y%m%d).log)"
./src/eod_update_cron.sh

echo ""
echo "Press Enter to close this window..."
read
