"""
stockbee_4pct_burst.py — Does buying the first 4% breakout day of a fresh
momentum burst work? (Pradeep Bonde / Stockbee "4% Momentum Burst" method.)

Event: at Day 0 close, ALL of:
  - Burst day: close >= 1.04 x yesterday's close.
  - Volume confirmation: volume > yesterday's volume AND volume >= 50d mean.
  - Fresh, not extended: each of the prior 3 daily closes gained <= 2%,
    and yesterday's close <= 1.08 x yesterday's 10d MA.
  - Out of consolidation: 5-day range as of yesterday
    ((5d max high - 5d min low) / close) <= 8%.
  - Tradeable (common.tradeable_mask) and no event in the prior 5 bars.

Sub-studies:
  1. Baseline forward returns from D+1 open (focus D+1/D+3/D+5 — 3-5 day method)
  2. Breadth regime + RS quintile segments (the core question)
  3. Burst magnitude (4-6% / 6-8% / >8%)
  4. Volume ratio vs 50d avg (1-1.5x / 1.5-3x / >3x)
  5. Close position in day's range (<0.7 vs >=0.7 — Bonde wants closes near highs)
  6. Above vs below 50d MA
  7. Rule-exit simulation: entry D+1 open, stop = signal-bar low (capped 6%
     below entry), time exit D+5 close (variant: D+3 close), by regime.

Usage:
    ~/anaconda3/bin/python src/backtest/studies/stockbee_4pct_burst.py
"""

import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))

import common


def find_events(m: dict) -> pd.DataFrame:
    close, high, low, volume = m["close"], m["high"], m["low"], m["volume"]

    chg = close.pct_change(fill_method=None)
    burst = chg >= 0.04

    vol_50d = volume.rolling(50).mean()
    vol_ok = (volume > volume.shift(1)) & (volume >= vol_50d)

    fresh = (chg.shift(1) <= 0.02) & (chg.shift(2) <= 0.02) & (chg.shift(3) <= 0.02)
    ma10 = close.rolling(10).mean()
    not_extended = close.shift(1) <= 1.08 * ma10.shift(1)

    range_5d = (high.rolling(5).max() - low.rolling(5).min()) / close
    consolidated = range_5d.shift(1) <= 0.08

    mask = (burst & vol_ok & fresh & not_extended & consolidated
            & common.tradeable_mask(close, volume))

    # Deduplicate: drop if the same symbol signalled in the prior 5 bars.
    recent = mask.shift(1, fill_value=False).rolling(5, min_periods=1).sum() > 0
    mask = mask & ~recent

    events = common.events_from_mask(mask, m)
    events = common.add_regime_and_rs_buckets(events)

    dates, syms = np.where(mask.reindex_like(close).fillna(False))
    events["burst_pct"] = chg.values[dates, syms] * 100
    events["vol_ratio_50d"] = (volume.values[dates, syms]
                               / vol_50d.values[dates, syms])
    day_range = high.values[dates, syms] - low.values[dates, syms]
    off_low = close.values[dates, syms] - low.values[dates, syms]
    events["close_pos"] = np.divide(off_low, day_range, where=day_range > 0,
                                    out=np.ones_like(day_range))
    ma50 = close.rolling(50).mean()
    events["above_50ma"] = close.values[dates, syms] > ma50.values[dates, syms]
    events["signal_low"] = low.values[dates, syms]
    events["date_idx"] = dates
    events["sym_idx"] = syms
    return events


def simulate_exits(events: pd.DataFrame, m: dict, hold_max: int) -> pd.DataFrame:
    """Entry D+1 open, stop = max(signal low, entry x 0.94), gap-through fills
    at the open, stop wins on ambiguity, else time exit at D+hold_max close."""
    O, H, L, C = (m[k].values for k in ("open", "high", "low", "close"))
    n_dates = O.shape[0]
    rows = []
    for ev in events.itertuples():
        d0, s = ev.date_idx, ev.sym_idx
        if d0 + 1 >= n_dates:
            continue
        entry = O[d0 + 1, s]
        if np.isnan(entry):
            continue
        stop = max(ev.signal_low, entry * 0.94)
        risk = entry - stop
        if risk <= 0:
            continue  # gapped below the signal low at entry — no defined risk
        exit_price, hold = np.nan, np.nan
        for d in range(1, hold_max + 1):
            if d0 + d >= n_dates or np.isnan(C[d0 + d, s]):
                break
            if L[d0 + d, s] <= stop:
                exit_price = min(O[d0 + d, s], stop)
                hold = d
                break
            if d == hold_max:
                exit_price, hold = C[d0 + d, s], d
        if np.isnan(exit_price):
            continue
        rows.append((ev.regime, (exit_price - entry) / risk, hold))
    return pd.DataFrame(rows, columns=["regime", "r", "hold"])


def print_sim_table(sim: pd.DataFrame, label: str) -> None:
    print(f"\n  {label}:")
    groups = [("ALL", sim)] + [(r, sim[sim["regime"] == r])
                               for r in ("bad", "neutral", "good")]
    for name, g in groups:
        if len(g) < 30:
            print(f"    {name:<10} n={len(g)} (too few)")
            continue
        pos, neg = g.loc[g["r"] > 0, "r"].sum(), g.loc[g["r"] < 0, "r"].sum()
        pf = pos / -neg if neg < 0 else np.inf
        print(f"    {name:<10} n={len(g):<6} win {(g['r'] > 0).mean() * 100:4.1f}%  "
              f"avg R {g['r'].mean():+5.2f}  med R {g['r'].median():+5.2f}  "
              f"PF {pf:4.2f}  hold {g['hold'].mean():.1f}d")


def print_report(events: pd.DataFrame, m: dict) -> None:
    print(f"\n{'=' * 76}")
    print(f"STOCKBEE 4% MOMENTUM BURST STUDY — "
          f"{events['date'].min().date()} → {events['date'].max().date()}")
    print(f"{'=' * 76}")
    print(f"Events: {len(events)}  (first 4%+ burst day out of a <=8% 5-day "
          f"consolidation)")
    print("Returns below are from D+1 OPEN entry to D+n close unless noted.")

    print("\n[1] Baseline forward returns (all events):")
    for n in common.HORIZONS:
        print(f"  D+{n:<3} {common.stat_line(events[f'ret_o{n}'])}")

    common.print_standard_segments(events, horizons=(1, 3, 5))

    events["burst_bucket"] = pd.cut(events["burst_pct"], [4, 6, 8, np.inf],
                                    labels=["4-6%", "6-8%", ">8%"],
                                    include_lowest=True)
    print("\n[3] By burst magnitude (Day 0 close-to-close gain):")
    common.print_table(events, "burst_bucket", horizons=(1, 3, 5))

    events["vol_bucket"] = pd.cut(events["vol_ratio_50d"], [1, 1.5, 3, np.inf],
                                  labels=["1-1.5x", "1.5-3x", ">3x"],
                                  include_lowest=True)
    print("\n[4] By volume ratio vs 50d average:")
    common.print_table(events, "vol_bucket", horizons=(1, 3, 5))

    events["close_pos_bucket"] = np.where(events["close_pos"] >= 0.7,
                                          "close >=0.7 of range",
                                          "close <0.7 of range")
    print("\n[5] By close position in day's range (Bonde wants closes near highs):")
    common.print_table(events, "close_pos_bucket", horizons=(1, 3, 5))

    events["trend"] = np.where(events["above_50ma"], "above 50 DMA", "below 50 DMA")
    print("\n[6] Trend context at Day 0:")
    common.print_table(events, "trend", horizons=(1, 3, 5))

    print("\n[7] Rule-exit simulation — entry D+1 open, stop = signal-bar low")
    print("    (capped 6% below entry), gap-through fills at open:")
    print_sim_table(simulate_exits(events, m, hold_max=5), "Time exit D+5 close")
    print_sim_table(simulate_exits(events, m, hold_max=3), "Time exit D+3 close")

    print(f"\n{common.CAVEATS}")


def main():
    m = common.load_cache()
    print(f"Cache: {m['close'].shape[1]} symbols, "
          f"{m['close'].index.min().date()} → {m['close'].index.max().date()}")

    print("Scanning for 4% momentum burst events...")
    events = find_events(m)
    print(f"  {len(events)} events")

    print_report(events, m)

    os.makedirs(common.OUTPUT_DIR, exist_ok=True)
    out_path = os.path.join(common.OUTPUT_DIR, "stockbee_4pct_burst_events.csv")
    events.drop(columns=["date_idx", "sym_idx"]).to_csv(out_path, index=False)
    print(f"\nEvent log → {out_path}")


if __name__ == "__main__":
    main()
