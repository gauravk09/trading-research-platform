"""
engine.py — Daily-bar trade simulation for the Qullamaggie breakout setup

Mechanically encodes SETUP_RULES.md on daily bars:
  - Signal: stock passes the breakout pre-scan at day T's close
  - Entry (day T+1): buy-stop at day T's high — fills at max(open, trigger)
    only if T+1's high trades above the trigger
  - Initial stop: low of entry day; trade skipped if wider than 1× ADR
  - Partial: sell 1/3 at 2.5R, move stop on the rest to breakeven
  - Trail: exit remaining shares on first close below the 10-day MA
  - Sizing: strategies/qullamaggie/position_sizing.calculate_position()

Fill assumptions (deliberately conservative / honest about daily bars):
  - Gap through stop fills at the OPEN, not the stop price
  - If stop and target are both touched the same day, the stop wins
  - Opening-range and breakout-volume confirmation need intraday data —
    not simulated; noted as a known optimistic bias
  - Initial stop uses the entry day's low, which is only fully known at
    that day's close — a mild approximation of "low of day so far"
"""

import os
import sys
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "strategies", "qullamaggie"))

from position_sizing import calculate_position
from backtest.pointintime import scan_asof

PARTIAL_R = 2.5          # take 1/3 off at 2.5R (midpoint of the 2-3R rule)
TRAIL_MA = 10            # exit remaining on first close below this MA
SIGNALS_PER_DAY = 10     # top candidates carried to the next day as buy-stops


def run_backtest(
    data:            dict,
    prescreens:      dict,
    rs_matrix:       pd.DataFrame,
    dates:           pd.DatetimeIndex,
    account_size:    float = 1_000_000,
    risk_pct:        float = 0.5,
    max_positions:   int = 5,
    min_turnover_cr: float = 1.0,
    min_rs_pct:      float = 60.0,
) -> tuple:
    """
    Simulate the breakout setup over `dates` (a trading calendar).

    Returns:
        trades_df: one row per completed trade
        equity_df: mark-to-market account value per day
    """
    bars = {s: df.set_index("date") for s, df in data.items()}
    ma10 = {s: df["close"].rolling(TRAIL_MA).mean().set_axis(df["date"]) for s, df in data.items()}

    cash = account_size
    open_positions = {}   # symbol -> position dict
    pending_signals = []  # candidates from yesterday's scan, awaiting trigger
    trades = []
    equity_curve = []

    def close_out(pos, exit_date, price, shares, reason):
        nonlocal cash
        cash += shares * price
        pos["realized"] += shares * (price - pos["entry"])
        pos["shares_left"] -= shares
        pos["exits"].append((exit_date, round(price, 2), shares, reason))
        if pos["shares_left"] == 0:
            init_risk = pos["init_risk_per_share"] * pos["init_shares"]
            trades.append({
                "symbol":      pos["symbol"],
                "entry_date":  pos["entry_date"].date(),
                "exit_date":   exit_date.date(),
                "entry":       round(pos["entry"], 2),
                "init_stop":   round(pos["init_stop"], 2),
                "shares":      pos["init_shares"],
                "pnl":         round(pos["realized"], 2),
                "r_multiple":  round(pos["realized"] / init_risk, 2) if init_risk > 0 else None,
                "hold_days":   pos["bars_held"],
                "exit_reason": reason,
                "exits":       "; ".join(f"{d.date()} {n}@{p} ({r})" for d, p, n, r in pos["exits"]),
            })
            del open_positions[pos["symbol"]]

    for t in dates:
        # ── 1. Manage open positions with today's bar ──────────────
        for pos in list(open_positions.values()):
            bar_df = bars[pos["symbol"]]
            if t not in bar_df.index:
                continue  # suspended/halted today — no fills possible
            bar = bar_df.loc[t]
            pos["bars_held"] += 1

            if bar["open"] <= pos["stop"]:
                close_out(pos, t, float(bar["open"]), pos["shares_left"], "stop_gap")
                continue
            if bar["low"] <= pos["stop"]:
                close_out(pos, t, pos["stop"], pos["shares_left"], "stop")
                continue

            if not pos["partial_done"] and pos["shares_left"] > 1:
                fill = None
                if bar["open"] >= pos["target"]:
                    fill = float(bar["open"])
                elif bar["high"] >= pos["target"]:
                    fill = pos["target"]
                if fill is not None:
                    partial_shares = max(1, pos["init_shares"] // 3)
                    close_out(pos, t, fill, partial_shares, "partial_2.5R")
                    pos["partial_done"] = True
                    pos["stop"] = pos["entry"]  # breakeven per the rules
                    continue  # skip MA-trail check on the partial day

            trail = ma10[pos["symbol"]].get(t)
            if pd.notna(trail) and bar["close"] < trail:
                close_out(pos, t, float(bar["close"]), pos["shares_left"], "ma_trail")

        # ── 2. Try to trigger yesterday's signals ──────────────────
        for sig in pending_signals:
            if len(open_positions) >= max_positions or sig["symbol"] in open_positions:
                continue
            bar_df = bars[sig["symbol"]]
            if t not in bar_df.index:
                continue
            bar = bar_df.loc[t]
            if bar["high"] <= sig["trigger"]:
                continue  # never traded above the breakout level today

            entry = max(float(bar["open"]), sig["trigger"])
            stop = float(bar["low"])
            stop_pct = (entry - stop) / entry * 100
            if stop <= 0 or entry - stop <= 0 or stop_pct > sig["adr_pct"]:
                continue  # stop wider than 1× ADR → skip trade entirely

            equity = cash + sum(
                p["shares_left"] * float(bars[p["symbol"]].loc[:t, "close"].iloc[-1])
                for p in open_positions.values()
            )
            sizing = calculate_position(equity, entry, stop, risk_pct=risk_pct)
            if not sizing.get("shares"):
                continue
            shares = min(sizing["shares"], int(cash / entry))
            if shares <= 0:
                continue

            cash -= shares * entry
            open_positions[sig["symbol"]] = {
                "symbol":              sig["symbol"],
                "entry_date":          t,
                "entry":               entry,
                "stop":                stop,
                "init_stop":           stop,
                "init_risk_per_share": entry - stop,
                "target":              entry + (entry - stop) * PARTIAL_R,
                "init_shares":         shares,
                "shares_left":         shares,
                "partial_done":        False,
                "realized":            0.0,
                "bars_held":           0,
                "exits":               [],
            }

        # ── 3. Scan at today's close → signals for tomorrow ───────
        pending_signals = []
        if len(open_positions) < max_positions:
            candidates = scan_asof(
                data, t, prescreens,
                rs_matrix=rs_matrix,
                min_turnover_cr=min_turnover_cr,
                min_rs_pct=min_rs_pct,
            )
            for _, row in candidates.head(SIGNALS_PER_DAY).iterrows():
                day_high = float(bars[row["symbol"]].loc[t, "high"])
                pending_signals.append({
                    "symbol":  row["symbol"],
                    "trigger": day_high,
                    "adr_pct": row["adr_pct"],
                })

        # ── 4. Mark to market ───────────────────────────────────────
        holdings = sum(
            p["shares_left"] * float(bars[p["symbol"]].loc[:t, "close"].iloc[-1])
            for p in open_positions.values()
        )
        equity_curve.append({"date": t, "equity": round(cash + holdings, 2),
                             "open_positions": len(open_positions)})

    # Force-close anything still open at the last bar so stats are complete
    last = dates[-1]
    for pos in list(open_positions.values()):
        price = float(bars[pos["symbol"]].loc[:last, "close"].iloc[-1])
        close_out(pos, last, price, pos["shares_left"], "end_of_backtest")

    trades_df = pd.DataFrame(trades)
    equity_df = pd.DataFrame(equity_curve).set_index("date")
    return trades_df, equity_df
