"""trade_tracker.py — Persist open Breakout-Setup trades and apply Bonde's exit rule.

Source: stockbee.blogspot.com "My swing trading process flow" — hold 3-5 days;
if the trade is in profit by day 3, move the stop up to protect the gain; exit
by day 5 regardless of outcome. Stop is fixed at the breakout day's low until then.

Format: {"SYMBOL": {entry_date, entry_price, initial_stop, current_stop,
                    status, day_count, last_eval_date}, ...}
Stored at data/processed/stockbee_trades.json — same pattern as watchlist_store.py.
"""

import json
import os

import pandas as pd

STORE = os.path.join(os.path.dirname(__file__), "..", "..", "data", "processed",
                     "stockbee_trades.json")

BREAKEVEN_DAY = 3  # Bonde: if profitable by day 3, tighten the stop
HARD_EXIT_DAY = 5  # Bonde: exit by day 5-6 regardless


def load_trades() -> dict:
    if not os.path.exists(STORE):
        return {}
    try:
        with open(STORE) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def save_trades(d: dict) -> None:
    os.makedirs(os.path.dirname(STORE), exist_ok=True)
    with open(STORE, "w") as f:
        json.dump(d, f, indent=2, sort_keys=True)


def open_trade(symbol: str, entry_date: str, entry_price: float, stop_price: float) -> dict:
    trades = load_trades()
    trades[symbol] = {
        "entry_date": entry_date,
        "entry_price": round(float(entry_price), 2),
        "initial_stop": round(float(stop_price), 2),
        "current_stop": round(float(stop_price), 2),
        "status": "open",
        "day_count": 0,
        "last_eval_date": entry_date,
    }
    save_trades(trades)
    return trades


def close_trade(symbol: str) -> dict:
    trades = load_trades()
    trades.pop(symbol, None)
    save_trades(trades)
    return trades


def evaluate_trades(universe: pd.DataFrame) -> pd.DataFrame:
    """Advance day-count for open trades on each new trading day and apply the
    day-3 breakeven / day-5 hard-exit rule. Returns a display-ready DataFrame.
    """
    trades = load_trades()
    rows = []
    for symbol, t in trades.items():
        if t["status"] not in ("open", "exit_due"):
            continue
        match = universe[universe["symbol"] == symbol]
        if match.empty:
            rows.append({**t, "symbol": symbol, "close": None, "action": "no data today"})
            continue
        r = match.iloc[0]

        if r["last_date"] == t["entry_date"]:
            # Same bar the trade was opened on — the stop *is* today's low by
            # definition, so there's nothing to evaluate until the next bar.
            rows.append({
                "symbol": symbol, "entry_date": t["entry_date"],
                "entry_price": t["entry_price"], "current_stop": t["current_stop"],
                "close": r["close"], "gain_pct": 0.0, "day_count": 0,
                "status": t["status"], "action": "entry day",
            })
            continue

        if r["last_date"] != t["last_eval_date"]:
            t["day_count"] += 1
            t["last_eval_date"] = r["last_date"]

        gain_pct = (float(r["close"]) - t["entry_price"]) / t["entry_price"] * 100
        action = "hold"

        if float(r["low"]) <= t["current_stop"]:
            t["status"] = "stopped"
            action = "stopped out"
        elif t["day_count"] >= BREAKEVEN_DAY and gain_pct > 0:
            new_stop = max(t["current_stop"], t["entry_price"])
            if new_stop > t["current_stop"]:
                t["current_stop"] = round(new_stop, 2)
                action = "stop moved to breakeven"
            if t["day_count"] >= HARD_EXIT_DAY:
                t["status"] = "exit_due"
                action = "exit due (day 5+)"
        elif t["day_count"] >= HARD_EXIT_DAY:
            t["status"] = "exit_due"
            action = "exit due (day 5+)"

        rows.append({
            "symbol": symbol,
            "entry_date": t["entry_date"],
            "entry_price": t["entry_price"],
            "current_stop": t["current_stop"],
            "close": r["close"],
            "gain_pct": round(gain_pct, 2),
            "day_count": t["day_count"],
            "status": t["status"],
            "action": action,
        })

    save_trades(trades)
    return pd.DataFrame(rows)
