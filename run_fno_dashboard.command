#!/bin/bash
# Double-click to start the dashboard directly on the F&O Board.
cd "$(dirname "$0")" || exit 1
exec ./run_dashboard.command "http://localhost:5173/?page=fno"
