"""
pocket_pivot.py — Pocket Pivot: does the Morales/Kacher early-entry volume
signature inside a base have an edge?

Source: Gil Morales & Chris Kacher, "Trade Like an O'Neil Disciple" (2010).
A pocket pivot is an up-day whose volume exceeds every down-day volume of the
prior 10 sessions, occurring in constructive context inside/near a base —
an early entry before the classic breakout.

Event = (symbol, date) where ALL hold at that day's close:
  Volume signature:
    - close > yesterday's close (up day)
    - volume > max volume among the DOWN days (close < prior close) of the
      prior 10 sessions (excluding today); no down days in window = no signal
  Constructive context:
    - close > SMA50 and SMA50 > SMA200 (uptrend)
    - SMA200 not falling: SMA200 today >= SMA200 21 bars ago
  In/near a base, not extended:
    - yesterday's close <= 1.05 x yesterday's SMA10
    - close within 10% of SMA50, OR close crosses up through SMA10
      (yesterday close < SMA10, today close > SMA10)
  Dedup: no event for the same symbol in the prior 5 bars.

Reported: forward returns from D+1 open at D+1/2/3/5/10/20; regime and RS
segments; sub-studies by pivot type (10dma-cross vs near-50dma), volume ratio
vs 50d avg, close position in the day's range; and a rule-exit simulation
(stop = min(pivot low, entry - 5%), exit on first close below SMA10 after
5 bars of room, max 40 bars).

Usage:
    ~/anaconda3/bin/python src/backtest/studies/pocket_pivot.py
"""

import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))

import common

MAX_HOLD = 40
MA_EXIT_ROOM = 5


def find_events(m: dict) -> pd.DataFrame:
    close, high, low, volume = m["close"], m["high"], m["low"], m["volume"]
    sma10 = close.rolling(10).mean()
    sma50 = close.rolling(50).mean()
    sma200 = close.rolling(200).mean()

    up_day = close > close.shift(1)
    down_day = close < close.shift(1)
    # Max down-day volume over the prior 10 sessions (excluding today);
    # NaN when no down days in the window, so the comparison fails = no signal.
    max_down_vol = volume.where(down_day).rolling(10, min_periods=1).max().shift(1)
    volume_signature = up_day & (volume > max_down_vol)

    uptrend = (close > sma50) & (sma50 > sma200) & (sma200 >= sma200.shift(21))
    not_extended = close.shift(1) <= 1.05 * sma10.shift(1)
    near_50 = (close / sma50 - 1).abs() <= 0.10
    cross_10 = (close.shift(1) < sma10.shift(1)) & (close > sma10)

    mask = (
        volume_signature
        & uptrend
        & not_extended
        & (near_50 | cross_10)
        & common.tradeable_mask(close, volume)
    )
    # Dedup: drop if the same symbol signalled in the prior 5 bars.
    mask &= ~mask.shift(1).rolling(5).max().fillna(0).astype(bool)

    events = common.events_from_mask(mask, m)
    events = common.add_regime_and_rs_buckets(events)

    dates, syms = np.where(mask.reindex_like(close).fillna(False))
    events["pivot_type"] = np.where(cross_10.values[dates, syms],
                                    "10dma cross", "near 50dma")
    events["vol_ratio"] = (volume / volume.rolling(50).mean()).values[dates, syms]
    rng = (high - low).values[dates, syms]
    with np.errstate(invalid="ignore", divide="ignore"):
        events["close_pos"] = np.where(
            rng > 0, (close.values[dates, syms] - low.values[dates, syms]) / rng, np.nan)
    events["pivot_low"] = low.values[dates, syms]
    events["date_idx"] = dates
    return events


def simulate_exits(events: pd.DataFrame, m: dict) -> pd.DataFrame:
    """Per event: enter D+1 open, stop = min(pivot low, entry - 5%), exit on
    first close below SMA10 after 5 bars of room, or stop hit, max 40 bars."""
    close, open_, low = m["close"], m["open"], m["low"]
    sma10 = close.rolling(10).mean()
    col_idx = {s: i for i, s in enumerate(close.columns)}
    n_dates = len(close.index)
    o, l, c, ma = (df.values for df in (open_, low, close, sma10))

    rows = []
    for ev in events.itertuples():
        j = col_idx[ev.symbol]
        start = ev.date_idx + 1
        if start >= n_dates or np.isnan(o[start, j]):
            continue
        entry = o[start, j]
        stop = min(ev.pivot_low, entry * 0.95)
        risk = entry - stop

        exit_r = hold = last_k = None
        for k in range(start, min(start + MAX_HOLD, n_dates)):
            if np.isnan(c[k, j]):
                break
            if o[k, j] <= stop:                       # gap through stop
                exit_r = (o[k, j] - entry) / risk
            elif l[k, j] <= stop:                     # stop wins same-bar ambiguity
                exit_r = (stop - entry) / risk
            elif k - start + 1 > MA_EXIT_ROOM and c[k, j] < ma[k, j]:
                exit_r = (c[k, j] - entry) / risk     # close below 10d MA
            if exit_r is not None:
                hold = k - start + 1
                break
            last_k = k
        if exit_r is None:                            # time/data-end exit at close
            if last_k is None:
                continue
            exit_r = (c[last_k, j] - entry) / risk
            hold = last_k - start + 1
        rows.append({"regime": ev.regime, "r": exit_r, "hold": hold})
    return pd.DataFrame(rows)


def print_sim_stats(label: str, sim: pd.DataFrame) -> None:
    if len(sim) < 30:
        print(f"  {label:<14} n={len(sim)} (too few)")
        return
    r = sim["r"]
    gains, losses = r[r > 0].sum(), -r[r <= 0].sum()
    pf = gains / losses if losses > 0 else np.inf
    print(f"  {label:<14} n={len(sim):<6} win {(r > 0).mean() * 100:4.1f}%  "
          f"avg {r.mean():+5.2f}R  med {r.median():+5.2f}R  "
          f"PF {pf:4.2f}  avg hold {sim['hold'].mean():4.1f}d")


def print_report(events: pd.DataFrame, sim: pd.DataFrame) -> None:
    print(f"\n{'=' * 76}")
    print(f"POCKET PIVOT STUDY — "
          f"{events['date'].min().date()} → {events['date'].max().date()}")
    print(f"{'=' * 76}")
    print(f"Events: {len(events)} | Returns are from D+1 OPEN entry to D+n close.")

    print("\n[1] Baseline forward returns (all events):")
    for n in common.HORIZONS:
        print(f"  D+{n:<3} {common.stat_line(events[f'ret_o{n}'])}")

    common.print_standard_segments(events)

    good = events[events["regime"] == "good"].copy()

    print("\n[3] Good market only — by pivot type:")
    common.print_table(good, "pivot_type")

    good["vol_bucket"] = pd.cut(good["vol_ratio"], [0, 1.5, 2.5, np.inf],
                                labels=["<1.5x 50d avg", "1.5-2.5x", ">2.5x"])
    print("\n[4] Good market only — by pivot-day volume vs 50d avg:")
    common.print_table(good, "vol_bucket")

    good["pos_bucket"] = pd.cut(good["close_pos"], [0, 0.5, 0.8, 1.0],
                                labels=["close <0.5 of range", "0.5-0.8", ">0.8"],
                                include_lowest=True)
    print("\n[5] Good market only — by pivot-day close position in range:")
    common.print_table(good, "pos_bucket")

    print("\n[6] Rule-exit simulation (entry D+1 open, stop = min(pivot low, -5%),")
    print("    exit close < SMA10 after 5 bars of room, max 40 bars):")
    print_sim_stats("all", sim)
    for regime in ["good", "neutral", "bad"]:
        print_sim_stats(regime, sim[sim["regime"] == regime])

    print()
    print(common.CAVEATS)


def main():
    m = common.load_cache()
    print(f"Cache: {m['close'].shape[1]} symbols, "
          f"{m['close'].index.min().date()} → {m['close'].index.max().date()}")

    events = find_events(m)
    print(f"Events found: {len(events)}")

    sim = simulate_exits(events, m)
    print_report(events, sim)

    os.makedirs(common.OUTPUT_DIR, exist_ok=True)
    out_path = os.path.join(common.OUTPUT_DIR, "pocket_pivot_events.csv")
    events.drop(columns=["date_idx"]).to_csv(out_path, index=False)
    print(f"\nEvent log → {os.path.abspath(out_path)}")


if __name__ == "__main__":
    main()
