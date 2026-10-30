#!/bin/zsh
# Refresh the Kite Connect access token (expires daily at 6 AM IST).
# Double-click this file in Finder, or run it from a terminal.
# It opens the Zerodha login in your browser, then asks for the request_token.

cd "$(dirname "$0")" || exit 1
$HOME/anaconda3/bin/python src/auth.py

echo ""
echo "Press Enter to close this window..."
read
