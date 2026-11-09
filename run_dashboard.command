#!/bin/bash
# Double-click to run the web dashboard (API + frontend), opens the browser.
# Close this terminal window to stop both servers.
cd "$(dirname "$0")"

# stop any previous instances so a re-run always works. The live scanner MUST
# be killed too, not reused: the Kite access token expires daily at 6 AM IST,
# so a scanner left running from yesterday holds a dead token and its websocket
# gets 403-Forbidden — the Live tables silently go empty. Restarting it here
# makes it reload today's token from .env.
# Kill by port AND by process name: a scanner/API that crashed its port bind
# but is still alive (holding a stale token) would survive a port-only kill.
lsof -ti:8700 | xargs kill 2>/dev/null
lsof -ti:5173 | xargs kill 2>/dev/null
lsof -ti:8602 | xargs kill 2>/dev/null
pkill -f "uvicorn webapp.server.main" 2>/dev/null
pkill -f "src/live_anticipation.py" 2>/dev/null
sleep 1

$HOME/anaconda3/bin/python3 -m uvicorn webapp.server.main:app --port 8700 &
API_PID=$!
npm --prefix webapp/frontend run dev &
WEB_PID=$!

# live intraday scanner — needs today's Kite token (run `PYTHONPATH=src python -m data_collection.kite.auth`
# first each morning). Harmless if it exits: the Live page shows "offline".
mkdir -p logs
$HOME/anaconda3/bin/python3 src/live_anticipation.py >> logs/live_scanner.log 2>&1 &
LIVE_PID=$!

# Independent NFO implied-volatility feed. If today's Kite token is unavailable
# it exits harmlessly; the F&O board remains usable and shows IV as offline.
$HOME/anaconda3/bin/python3 src/fno_iv.py >> logs/fno_iv.log 2>&1 &
IV_PID=$!

trap "kill $API_PID $WEB_PID $LIVE_PID $IV_PID 2>/dev/null" EXIT
sleep 3
DASHBOARD_URL="${1:-http://localhost:5173}"
open "$DASHBOARD_URL"

echo ""
echo "Dashboard running at $DASHBOARD_URL — close this window to stop."
wait
