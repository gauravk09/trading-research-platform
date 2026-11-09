"""
kite_account.py — live account snapshot (margins, positions, holdings) via
the KiteConnect API, using the same .env access token as auth.py.

Used by the /brief skill instead of the Kite MCP, which has proven
unreliable (frequent "please log in first" failures even with a valid
token). Run directly to print the snapshot as JSON.
"""

import json
import sys
from datetime import datetime

from data_collection.kite.auth import get_kite_client


def get_account_snapshot():
    kite = get_kite_client()

    available_balance = kite.margins("equity")["available"]["live_balance"]

    positions = [
        {
            "symbol": p["tradingsymbol"],
            "exchange": p["exchange"],
            "product": p["product"],
            "quantity": p["quantity"],
            "average_price": p["average_price"],
            "last_price": p["last_price"],
            "pnl": p["pnl"],
        }
        for p in kite.positions()["net"]
        if p["quantity"] != 0
    ]

    holdings = [
        {
            "symbol": h["tradingsymbol"],
            "quantity": h["quantity"] + h.get("t1_quantity", 0),
            "average_price": h["average_price"],
            "last_price": h["last_price"],
            "pnl": h["pnl"],
        }
        for h in kite.holdings()
        if h["quantity"] + h.get("t1_quantity", 0) > 0
    ]

    return {
        "fetched_at": datetime.now().isoformat(timespec="seconds"),
        "available_balance": available_balance,
        "positions": positions,
        "holdings": holdings,
    }


if __name__ == "__main__":
    try:
        print(json.dumps(get_account_snapshot(), indent=2))
    except Exception as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)
