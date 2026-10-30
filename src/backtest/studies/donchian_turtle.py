"""
donchian_turtle.py — Does the Turtle 20-day Donchian breakout work long-only on NSE?

Source: Richard Dennis & William Eckhardt's Turtle rules, as documented in
Curtis Faith, "Way of the Turtle" (2007). System 1: buy a 20-day-high
breakout, initial stop 2N (N = 20-day ATR), exit on a 10-day low.
System 2 variant: 55-day-high entry, 20-day-low exit.

Event: today's HIGH exceeds the max high of the prior 20 bars (signal day).
Long only (no positional shorting of NSE cash equities). Dedup: one event
per symbol per 10 bars. Tradeability: common.tradeable_mask on signal day.

Turtles entered intraday at the level, on futures, with leverage, both
directions; this tests the long-only cash-equity translation with entry
modelled at D+1 open. Sensitivity check: fill at max(D+1 open, breakout
level) only when D+1 high > level — both reported.

Reported:
  1. Forward returns from D+1 open at D+1/2/3/5/10/20/40/60 (+ buy-stop fills)
  2. Breadth-regime and RS-quintile segments (the mandatory cuts)
  3. Sub-studies: S1 (20d) vs S2 (55d); ATR20 as % of close; 200 DMA side
  4. Rule-exit simulation (the real Turtle test): entry D+1 open,
     N = ATR20 (simple mean of true range, not Wilder) at signal day,
     initial stop = entry - 2N (fixed, no pyramiding), exit when LOW breaks
     the 10-day min low as of the prior bar (20-day for S2) — channel exit
     fills at min(open, level), gap through the stop fills at open, stop
     wins on ambiguity, force-exit at 120 bars close — by regime, S1 and S2.

Usage:
    ~/anaconda3/bin/python src/backtest/studies/donchian_turtle.py
"""

import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import common

ENTRY_LOOKBACK = {"S1": 20, "S2": 55}
EXIT_LOOKBACK = {"S1": 10, "S2": 20}
DEDUP_BARS = 10
STOP_N = 2.0
MAX_HOLD = 120
LONG_HORIZONS = [40, 60]


def dedup_mask(raw: pd.DataFrame, gap: int) -> pd.DataFrame:
    """Keep a signal only if the previous kept signal (same symbol) is more
    than `gap` rows back. Rows ≈ bars (shared NSE calendar)."""
    arr = raw.to_numpy()
    out = np.zeros_like(arr)
    for j in range(arr.shape[1]):
        last = -gap - 1
        for r in np.flatnonzero(arr[:, j]):
            if r - last > gap:
                out[r, j] = True
                last = r
    return pd.DataFrame(out, index=raw.index, columns=raw.columns)


def atr20(m: dict) -> pd.DataFrame:
    """Simple 20-bar mean of true range (not Wilder smoothing)."""
    h, l, pc = m["high"], m["low"], m["close"].shift(1)
    tr = np.maximum(h - l, np.maximum((h - pc).abs(), (l - pc).abs()))
    return tr.rolling(20).mean()


def build_events(m: dict, atr: pd.DataFrame, system: str) -> pd.DataFrame:
    """Donchian breakout events for one system, tagged with level, N,
    ATR%, 200 DMA side, buy-stop fills and long-horizon returns."""
    high, close = m["high"], m["close"]
    level = high.shift(1).rolling(ENTRY_LOOKBACK[system]).max()
    raw = (high > level) & common.tradeable_mask(close, m["volume"])
    mask = dedup_mask(raw.fillna(False), DEDUP_BARS)

    events = common.events_from_mask(mask, m)
    dates, syms = np.where(mask.reindex_like(close).fillna(False))
    events["level"] = level.values[dates, syms]
    events["n_atr"] = atr.values[dates, syms]
    events["atr_pct"] = events["n_atr"] / events["close"] * 100
    ma200 = close.rolling(200).mean()
    events["above_200ma"] = close.values[dates, syms] > ma200.values[dates, syms]

    d1_high = high.shift(-1).values[dates, syms]
    filled = d1_high > events["level"]
    events["buystop_fill"] = np.where(
        filled, np.maximum(events["entry_open"], events["level"]), np.nan)
    for n in [1, 5, 20]:
        fwd_close = close.shift(-n).values[dates, syms]
        events[f"ret_f{n}"] = (fwd_close / events["buystop_fill"] - 1) * 100
    for n in LONG_HORIZONS:
        fwd_close = close.shift(-n).values[dates, syms]
        events[f"ret_o{n}"] = (fwd_close / events["entry_open"] - 1) * 100

    events["system"] = system
    return common.add_regime_and_rs_buckets(events)


def simulate_rule_exits(events: pd.DataFrame, m: dict,
                        exit_lookback: int) -> pd.DataFrame:
    """Turtle exit sim: entry D+1 open, stop = entry - 2N (fixed), exit when
    LOW breaks the exit_lookback-day min low as of the prior bar. Channel
    exit fills at min(open, level); gap through stop fills at open; stop
    wins on ambiguity; force-exit at MAX_HOLD bars close."""
    close = m["close"]
    O, L, C = (m[k].to_numpy() for k in ["open", "low", "close"])
    channel = m["low"].rolling(exit_lookback).min().shift(1).to_numpy()
    date_pos = {d: i for i, d in enumerate(close.index)}
    sym_pos = {s: j for j, s in enumerate(close.columns)}
    n_rows = len(close.index)

    trades = []
    for ev in events.itertuples():
        i, j = date_pos[ev.date], sym_pos[ev.symbol]
        if i + 1 >= n_rows or np.isnan(O[i + 1, j]):
            continue
        if np.isnan(ev.n_atr) or ev.n_atr <= 0:
            continue
        entry = O[i + 1, j]
        risk = STOP_N * ev.n_atr
        stop = entry - risk

        exit_price, hold, reason = np.nan, np.nan, "open"
        last_close, last_k = np.nan, i + 1
        for k in range(i + 1, min(i + 1 + MAX_HOLD, n_rows)):
            if np.isnan(C[k, j]):
                continue
            last_close, last_k = C[k, j], k
            if O[k, j] <= stop:
                exit_price, hold, reason = O[k, j], k - i, "stop_gap"
                break
            if L[k, j] <= stop:
                exit_price, hold, reason = stop, k - i, "stop"
                break
            ch = channel[k, j]
            if not np.isnan(ch) and L[k, j] < ch:
                exit_price = O[k, j] if O[k, j] < ch else ch
                hold, reason = k - i, "channel"
                break
        if reason == "open":
            if np.isnan(last_close):
                continue
            exit_price, hold, reason = last_close, last_k - i, "timeout"

        trades.append({"date": ev.date, "symbol": ev.symbol,
                       "regime": ev.regime, "entry": entry,
                       "exit": exit_price,
                       "R": (exit_price - entry) / risk,
                       "hold": hold, "reason": reason})
    return pd.DataFrame(trades)


def print_exit_table(trades: pd.DataFrame) -> None:
    def line(name, grp):
        if len(grp) < 10:
            print(f"  {name:<14} n={len(grp)} (too few)")
            return
        r = grp["R"]
        pos, neg = r[r > 0].sum(), r[r < 0].sum()
        pf = pos / -neg if neg < 0 else np.inf
        print(f"  {name:<14} n={len(grp):<6} win {(r > 0).mean() * 100:4.1f}%  "
              f"avg R {r.mean():+5.2f}  med R {r.median():+5.2f}  "
              f"PF {pf:4.2f}  hold {grp['hold'].mean():4.1f}d")

    line("all", trades)
    for regime in ["good", "neutral", "bad"]:
        line(regime, trades[trades["regime"] == regime])
    reasons = trades["reason"].value_counts()
    print("  exits: " + ", ".join(f"{k} {v}" for k, v in reasons.items()))


def print_report(s1: pd.DataFrame, s2: pd.DataFrame,
                 trades1: pd.DataFrame, trades2: pd.DataFrame) -> None:
    print(f"\n{'=' * 76}")
    print(f"DONCHIAN TURTLE BREAKOUT STUDY (long-only) — "
          f"{s1['date'].min().date()} → {s1['date'].max().date()}")
    print(f"{'=' * 76}")
    filled = s1["buystop_fill"].notna()
    print(f"Events: S1 (20d high) {len(s1)} | S2 (55d high) {len(s2)} | "
          f"S1 buy-stop fill on D+1: {filled.sum()} ({filled.mean() * 100:.0f}%)")
    print("Returns below are from D+1 OPEN entry to D+n close unless noted.")

    print("\n[1] S1 baseline forward returns (all events, D+1 open entry):")
    for n in common.HORIZONS + LONG_HORIZONS:
        print(f"  D+{n:<3} {common.stat_line(s1[f'ret_o{n}'])}")

    print(f"\n[1b] Buy-stop sensitivity — fill at max(D+1 open, level) only")
    print(f"     when D+1 high > level ({filled.sum()} fills):")
    for n in [1, 5, 20]:
        print(f"  D+{n:<3} {common.stat_line(s1[f'ret_f{n}'])}")

    common.print_standard_segments(s1, horizons=[1, 5, 20])

    print("\n[3a] S1 (20d) vs S2 (55d) — longer horizons:")
    for name, ev in [("S1 20d high", s1), ("S2 55d high", s2)]:
        cells = "  |  ".join(f"D+{n} {common.stat_line(ev[f'ret_o{n}'])}"
                             for n in [5, 20, 60])
        print(f"  {name:<22} n={len(ev):<6} {cells}")

    print("\n[3b] S1 by ATR20 as % of close (quiet vs volatile names):")
    s1["atr_bucket"] = pd.cut(s1["atr_pct"], [0, 2, 4, np.inf],
                              labels=["<2%", "2-4%", ">4%"])
    common.print_table(s1, "atr_bucket", horizons=[1, 5, 20])

    print("\n[3c] S1 by 200 DMA side at signal:")
    s1["trend"] = np.where(s1["above_200ma"], "above 200 DMA", "below 200 DMA")
    common.print_table(s1, "trend", horizons=[1, 5, 20])

    print("\n[4] Rule-exit simulation — entry D+1 open, stop = entry - 2N")
    print("    (N = simple ATR20), exit on channel-low break, max 120 bars.")
    print("  S1: 20d-high entry, 10d-low exit:")
    print_exit_table(trades1)
    print("  S2: 55d-high entry, 20d-low exit:")
    print_exit_table(trades2)

    print()
    print(common.CAVEATS)


def main():
    print("Loading study cache...")
    m = common.load_cache()
    atr = atr20(m)

    print("Scanning for Donchian breakouts (S1 20d, S2 55d)...")
    s1 = build_events(m, atr, "S1")
    s2 = build_events(m, atr, "S2")
    print(f"  S1: {len(s1)} events | S2: {len(s2)} events")

    print("Simulating Turtle rule exits...")
    trades1 = simulate_rule_exits(s1, m, EXIT_LOOKBACK["S1"])
    trades2 = simulate_rule_exits(s2, m, EXIT_LOOKBACK["S2"])

    print_report(s1, s2, trades1, trades2)

    os.makedirs(common.OUTPUT_DIR, exist_ok=True)
    out_path = os.path.join(common.OUTPUT_DIR, "donchian_turtle_events.csv")
    pd.concat([s1, s2], ignore_index=True).to_csv(out_path, index=False)
    print(f"\nEvent log → {os.path.abspath(out_path)}")


if __name__ == "__main__":
    main()
