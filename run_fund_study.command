#!/bin/bash
# Standalone SBI Contra Fund research dashboard.
# Uses separate ports so the trading dashboard can keep running.
cd "$(dirname "$0")"

API_PORT=8710
WEB_PORT=5180

lsof -ti:$API_PORT | xargs kill 2>/dev/null
lsof -ti:$WEB_PORT | xargs kill 2>/dev/null

echo "Refreshing SBI Contra Fund disclosures..."
PYTHONPATH=src $HOME/anaconda3/bin/python3 src/fund_behavior_study.py collect 5

$HOME/anaconda3/bin/python3 -m uvicorn webapp.server.main:app --port $API_PORT &
API_PID=$!
VITE_API_TARGET="http://127.0.0.1:$API_PORT" npm --prefix webapp/frontend run dev -- --port $WEB_PORT &
WEB_PID=$!

trap "kill $API_PID $WEB_PID 2>/dev/null" EXIT
sleep 3
STUDY_URL="http://localhost:$WEB_PORT/fund-study"
open "$STUDY_URL"

echo ""
echo "Fund study running at $STUDY_URL — close this window to stop."
wait
