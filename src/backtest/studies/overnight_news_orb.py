"""
overnight_news_orb.py — Does after-close material news predict the next day?

Replays src/scanners/overnight_news.py's deterministic scorer over the backfilled
announcement history (2015+, financials 2017+) and measures, per trade day:

  gap%      open vs prior close — does score direction predict the gap?
  d0/1/5/20 close returns from the Day-T OPEN (buy-the-open baseline)

Selection uses ONLY information available before Day T's open (filing text,
timestamps, previously filed financials) — no look-ahead, unlike the
volume-spike study. Liquidity is measured point-in-time from trailing bars.

Writes output/studies/overnight_news_events.csv, which plugs directly into
the intraday ORB-entry engine for the real entry test:

    python src/backtest/studies/ep_intraday_orh.py \
        --events output/studies/overnight_news_events.csv --since 2024-01-01

Usage:
    python src/backtest/studies/overnight_news_orb.py --since 2018-01-01 \
        --min-score 1.5 --min-turnover 10
"""

import argparse
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from scanners.overnight_news import CLOSE_TIME, OPEN_TIME, load_financials, score_filings, window_filings
from data_collection.storage import read_daily

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "..", "output", "studies")

_daily_cache = {}


def daily(symbol: str) -> pd.DataFrame:
    if symbol not in _daily_cache:
        df = read_daily(symbol)
        if not df.empty:
            df = df.assign(day=df["date"].astype(str).str[:10])
        _daily_cache[symbol] = df
    return _daily_cache[symbol]


def outcome(symbol: str, day: str, min_turnover_cr: float) -> dict:
    """Point-in-time liquidity gate + open-entry forward returns for Day T."""
    df = daily(symbol)
    if df.empty:
        return None
    pos = df["day"].searchsorted(day)
    if pos >= len(df) or df["day"].iloc[pos] != day or pos < 21:
        return None

    hist = df.iloc[pos - 20:pos]
    turnover_cr = float((hist["close"] * hist["volume"]).mean() / 1e7)
    prev_close = float(df["close"].iloc[pos - 1])
    if turnover_cr < min_turnover_cr or prev_close < 30:
        return None

    open_t = float(df["open"].iloc[pos])
    out = {"turnover_cr": round(turnover_cr, 1),
           "gap_pct": round((open_t / prev_close - 1) * 100, 2),
           "open": open_t}
    for h in (0, 1, 5, 20):
        if pos + h < len(df):
            out[f"ret_{h}d"] = round((float(df["close"].iloc[pos + h]) / open_t - 1) * 100, 2)
        else:
            out[f"ret_{h}d"] = np.nan
    return out


def build_events(sessions, min_score: float, min_turnover_cr: float) -> pd.DataFrame:
    fin = load_financials()
    rows = []
    for i in range(1, len(sessions)):
        prev_d, d = sessions[i - 1].date(), sessions[i].date()
        start = pd.Timestamp(f"{prev_d} {CLOSE_TIME}")
        end = pd.Timestamp(f"{d} {OPEN_TIME}")

        scored = score_filings(window_filings(prev_d, d), fin, start, end)
        if scored.empty:
            continue
        scored = scored[scored["score"].abs() >= min_score]

        for ev in scored.itertuples():
            res = outcome(ev.symbol, str(d), min_turnover_cr)
            if res is None:
                continue
            rows.append({"symbol": ev.symbol, "date": str(d), "score": round(ev.score, 2),
                         "direction": ev.direction, "catalyst": ev.categories,
                         "reasons": ev.reasons, **res})
        if i % 250 == 0:
            print(f"  [{i}/{len(sessions) - 1}] {d} — {len(rows)} events so far")
    return pd.DataFrame(rows)


def print_report(events: pd.DataFrame) -> None:
    print(f"\n{'=' * 68}")
    print(f"OVERNIGHT NEWS → NEXT DAY, {len(events)} events "
          f"({events['date'].min()} → {events['date'].max()})")
    print(f"{'=' * 68}")

    for sign, label in ((1, "POSITIVE news"), (-1, "NEGATIVE news")):
        g = events[np.sign(events["score"]) == sign]
        if g.empty:
            continue
        print(f"\n{label} (n={len(g)}):")
        print(f"  gap at open:  median {g['gap_pct'].median():+.2f}%  "
              f"gap>0 {(g['gap_pct'] > 0).mean() * 100:.0f}%  "
              f"gap>3% {(g['gap_pct'] > 3).mean() * 100:.0f}%")
        for h in (0, 1, 5, 20):
            r = g[f"ret_{h}d"].dropna()
            print(f"  open→D+{h:<2} close: mean {r.mean():+.2f}%  median {r.median():+.2f}%  "
                  f"win {(r > 0).mean() * 100:.1f}%  (n={len(r)})")

    pos = events[events["score"] > 0]
    if len(pos) > 50:
        print("\nPositive events by score band (open→D+5 median / win / n):")
        for lo, hi in ((1.0, 2.0), (2.0, 3.0), (3.0, 99.0)):
            band = pos[(pos["score"] >= lo) & (pos["score"] < hi)]["ret_5d"].dropna()
            if len(band) >= 20:
                print(f"  score {lo:.0f}–{hi if hi < 99 else '+':<4} "
                      f"{band.median():+6.2f}%  {(band > 0).mean() * 100:5.1f}%  n={len(band)}")
        print("\nPositive events by catalyst (open→D+5 median / win / n):")
        for cat, grp in pos.groupby("catalyst"):
            band = grp["ret_5d"].dropna()
            if len(band) >= 25:
                print(f"  {cat:<28} {band.median():+6.2f}%  "
                      f"{(band > 0).mean() * 100:5.1f}%  n={len(band)}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--since", default="2018-01-01")
    parser.add_argument("--until", default=None)
    parser.add_argument("--min-score", type=float, default=1.5)
    parser.add_argument("--min-turnover", type=float, default=10.0)
    args = parser.parse_args()

    # trading calendar from a never-suspended bellwether (close_matrix only starts 2020)
    cal = read_daily("RELIANCE")["date"].astype(str).str[:10]
    cal = pd.to_datetime(cal[cal >= args.since])
    if args.until:
        cal = cal[cal <= pd.Timestamp(args.until)]
    sessions = cal.reset_index(drop=True)
    print(f"{len(sessions)} sessions {sessions.iloc[0].date()} → {sessions.iloc[-1].date()}")

    events = build_events(sessions, args.min_score, args.min_turnover)
    if events.empty:
        print("No events.")
        return

    print_report(events)
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    out_path = os.path.join(OUTPUT_DIR, "overnight_news_events.csv")
    events.to_csv(out_path, index=False)
    print(f"\nEvents → {out_path}")
    print("Intraday ORB entry test:  python src/backtest/studies/ep_intraday_orh.py "
          "--events output/studies/overnight_news_events.csv --since 2024-01-01")


if __name__ == "__main__":
    main()
