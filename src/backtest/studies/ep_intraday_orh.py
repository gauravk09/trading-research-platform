"""
ep_intraday_orh.py — Phase 3: intraday ORH entry test for EP events

Phase 1 approximated the EP entry as "buy Day 1 open, stop at Day 0 low" —
a wide stop that produced a 72.6% stop-out rate. This study tests the entry
the EP9M article actually used: buy Day 0's opening-range-high (ORH) break,
stop at the day's low-so-far at entry time. Same trade, measured properly.

Honest look-ahead note (shared with the article): events were selected by
FULL-DAY volume >= 3x average, which isn't fully knowable at the ORH break.
A live trader proxies it with gap size + early relative volume. Results are
therefore an upper bound on live performance.

Per event, one Kite request fetches Day 0 minute candles, cached to
data/raw/intraday/minute_day0/<SYMBOL>_<DATE>.csv (empty file = known no-data,
so re-runs never re-fetch). Kite serves minute data back to ~2015.

Trade rules:
    OR window = first 15 minutes (09:15-09:29). Entry at ORH the first time a
    later minute trades above it; no trigger = no trade. Stop = low-so-far at
    entry. Day 0: stopped intraday if a post-entry minute low touches the stop.
    Day 1+: daily-bar walk, gap through stop exits at the open, else exit at
    the D+60 close. Unstopped D+20 return recorded for comparison with Phase 1.

Usage (needs a fresh Kite token — python src/auth.py):
    python src/backtest/studies/ep_intraday_orh.py \
        --events output/studies/ep_events_with_catalyst.csv --since 2024-01-01
    Add --limit 50 for a quick test run.
"""

import os
import sys
import time
import argparse
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from storage import read_daily

CACHE_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "..", "data", "raw", "intraday", "minute_day0")
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "..", "output", "studies")

OR_MINUTES = 15
MAX_HORIZON = 60


def cached_minute_day(kite, token_map: dict, symbol: str, day: str) -> pd.DataFrame:
    """Day 0 minute candles, fetched once and cached. Empty df = no data."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = os.path.join(CACHE_DIR, f"{symbol}_{day}.csv")
    if os.path.exists(path):
        if os.path.getsize(path) == 0:
            return pd.DataFrame()
        return pd.read_csv(path, parse_dates=["date"])

    token = token_map.get(symbol.upper())
    if token is None:
        open(path, "w").close()  # delisted — remember the miss
        return pd.DataFrame()

    try:
        candles = kite.historical_data(token, from_date=day, to_date=day, interval="minute")
    except Exception as e:
        # stale/recycled instrument token etc. — remember the miss, keep going
        print(f"  {symbol} {day}: fetch failed ({e}) — marked no-data")
        open(path, "w").close()
        return pd.DataFrame()
    finally:
        time.sleep(0.35)  # Kite historical API allows ~3 req/s
    df = pd.DataFrame(candles)
    if df.empty:
        open(path, "w").close()
        return df
    df["date"] = pd.to_datetime(df["date"])
    df.to_csv(path, index=False)
    return df


def orh_trade(minute_df: pd.DataFrame) -> dict:
    """Entry/stop from Day 0 minute candles; None if the ORH never breaks."""
    if len(minute_df) < OR_MINUTES + 1:
        return None
    opening = minute_df.iloc[:OR_MINUTES]
    orh = float(opening["high"].max())

    rest = minute_df.iloc[OR_MINUTES:]
    trigger = rest[rest["high"] > orh]
    if trigger.empty:
        return None
    entry_idx = trigger.index[0]

    lows_until_entry = minute_df.loc[:entry_idx, "low"]
    stop = float(lows_until_entry.min())

    post_entry = minute_df.loc[entry_idx:].iloc[1:]
    stopped_day0 = bool((post_entry["low"] <= stop).any()) if not post_entry.empty else False

    return {
        "entry": orh,
        "stop": stop,
        "stop_pct": (orh - stop) / orh * 100,
        "entry_time": str(minute_df.loc[entry_idx, "date"])[11:16],
        "stopped_day0": stopped_day0,
        "day0_close": float(minute_df["close"].iloc[-1]),
    }


def walk_forward(daily: pd.DataFrame, day0_pos: int, entry: float, stop: float) -> dict:
    """Daily-bar exit walk from Day 1 (same rules as Phase 1's stopped mode)."""
    closes, lows, opens = daily["close"].values, daily["low"].values, daily["open"].values
    last_pos = min(day0_pos + 1 + MAX_HORIZON, len(daily) - 1)

    out = {"stopped": False, "exit_ret": np.nan, "exit_day": np.nan,
           "ret_5d": np.nan, "ret_20d": np.nan}
    for h in (5, 20):
        if day0_pos + h + 1 < len(daily):
            out[f"ret_{h}d"] = (float(closes[day0_pos + h + 1]) - entry) / entry * 100

    for day in range(day0_pos + 1, last_pos + 1):
        if lows[day] <= stop:
            exit_price = min(float(opens[day]), stop)
            out.update(stopped=True, exit_ret=(exit_price - entry) / entry * 100,
                       exit_day=day - day0_pos)
            return out
    if last_pos == day0_pos + 1 + MAX_HORIZON:
        out.update(exit_ret=(float(closes[last_pos]) - entry) / entry * 100,
                   exit_day=MAX_HORIZON)
    return out


def run(events: pd.DataFrame, limit: int) -> pd.DataFrame:
    from auth import get_kite_client
    from updater import _build_token_map

    kite = get_kite_client()
    kite.profile()  # fail fast on expired token
    token_map = _build_token_map()

    rows, no_data, no_trigger = [], 0, 0
    for i, ev in enumerate(events.itertuples(), start=1):
        if limit and len(rows) >= limit:
            break
        if i % 200 == 0:
            print(f"  [{i}/{len(events)}] trades={len(rows)} no_data={no_data} no_trigger={no_trigger}")

        day = str(ev.date)[:10]
        minute_df = cached_minute_day(kite, token_map, ev.symbol, day)
        if minute_df.empty:
            no_data += 1
            continue
        trade = orh_trade(minute_df)
        if trade is None:
            no_trigger += 1
            continue

        daily = read_daily(ev.symbol)
        day0_pos = daily["date"].astype(str).str[:10].searchsorted(day)
        if day0_pos >= len(daily) or str(daily["date"].iloc[day0_pos])[:10] != day:
            no_data += 1
            continue

        row = {"symbol": ev.symbol, "date": day, "catalyst": getattr(ev, "catalyst", ""),
               "entry": round(trade["entry"], 2), "entry_time": trade["entry_time"],
               "stop_pct": round(trade["stop_pct"], 2)}

        if trade["stopped_day0"]:
            row.update(stopped=True, exit_day=0,
                       exit_ret=round((trade["stop"] - trade["entry"]) / trade["entry"] * 100, 2),
                       ret_5d=np.nan, ret_20d=np.nan)
        else:
            fwd = walk_forward(daily, day0_pos, trade["entry"], trade["stop"])
            row.update(stopped=fwd["stopped"], exit_day=fwd["exit_day"],
                       **{k: round(fwd[k], 2) if pd.notna(fwd[k]) else np.nan
                          for k in ("exit_ret", "ret_5d", "ret_20d")})
        rows.append(row)

    print(f"Done: {len(rows)} trades, {no_data} events without data, {no_trigger} never broke ORH")
    return pd.DataFrame(rows)


def print_report(trades: pd.DataFrame) -> None:
    r = trades["exit_ret"].dropna()
    stopped = trades.loc[r.index, "stopped"]
    print(f"\n{'=' * 64}")
    print(f"INTRADAY ORH ENTRY — {len(trades)} triggered trades")
    print(f"{'=' * 64}")
    print(f"  median stop distance {trades['stop_pct'].median():.1f}% "
          f"(Phase 1 daily approximation was much wider)")
    print(f"  stopped-out rate {stopped.mean() * 100:.1f}% "
          f"(of which day-0: {(trades['exit_day'] == 0).mean() * 100:.1f}%)")
    print(f"  exit return: mean {r.mean():+.2f}%  median {r.median():+.2f}%  "
          f"win {(r > 0).mean() * 100:.1f}%")
    print(f"  avg loss when stopped {r[stopped].mean():+.2f}%  "
          f"avg when not stopped {r[~stopped].mean():+.2f}%")

    for h in (5, 20):
        u = trades[f"ret_{h}d"].dropna()
        if not u.empty:
            print(f"  unstopped D+{h} from ORH entry: median {u.median():+.1f}%  "
                  f"win {(u > 0).mean() * 100:.1f}%")
    ed = trades.loc[trades["stopped"], "exit_day"].dropna()
    if not ed.empty:
        print(f"  when stopped, median day of stop-out: D+{ed.median():.0f}")

    if "catalyst" in trades.columns and trades["catalyst"].nunique() > 1:
        print("\n  By catalyst (mean exit return / n):")
        for cat, grp in trades.groupby("catalyst"):
            g = grp["exit_ret"].dropna()
            if len(g) >= 15:
                print(f"    {cat or 'technical_only':<15} {g.mean():+6.2f}%  n={len(g)}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--events", required=True, help="Event CSV from phase 1 or 2")
    parser.add_argument("--since", default="2024-01-01", help="Only events on/after this date")
    parser.add_argument("--limit", type=int, default=None, help="Stop after N triggered trades (test runs)")
    args = parser.parse_args()

    events = pd.read_csv(args.events, parse_dates=["date"])
    events = events[events["date"] >= pd.Timestamp(args.since)]  # CSV dates are tz-naive
    events = events.sort_values("date").reset_index(drop=True)
    print(f"{len(events)} events since {args.since}")

    trades = run(events, args.limit)
    if trades.empty:
        print("No trades measured.")
        return

    print_report(trades)
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    out_path = os.path.join(OUTPUT_DIR, "ep_intraday_orh.csv")
    trades.to_csv(out_path, index=False)
    print(f"\nTrade log → {out_path}")


if __name__ == "__main__":
    main()
