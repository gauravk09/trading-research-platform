"""
weinstein_stage2.py — Does the Weinstein Stage 2 breakout have an edge on NSE?

Source: Stan Weinstein, "Secrets for Profiting in Bull and Bear Markets" (1988).
The classic stage-analysis entry: buy when a stock emerges from a Stage 1 base
through its 30-week MA on a big volume expansion.

Daily proxy of the weekly method. An event = (symbol, date) where at the close:
  - MA150 cross: close > 150d MA today, close <= 150d MA yesterday
  - Flat prior base: |MA150 / MA150 63 bars ago - 1| <= 3% (Stage 1, not Stage 4)
  - Time under: close <= MA150 on >= 40 of the prior 60 bars
  - Clears resistance: close > 0.98 x 126-day rolling max close as of yesterday
  - Volume expansion: volume >= 1.5x 50d mean (primary; 2x reported separately —
    Weinstein's non-negotiable — and segmented by ratio bucket)
  - Dedup: no event for the same symbol in the prior 20 bars
Tradeability: common.tradeable_mask (price/turnover/history floors).

Reported:
  1. Forward returns from D+1 open at D+1/2/3/5/10/20/40/60
  2. Breadth-regime and RS-quintile segments (the mandatory cuts)
  3. Sub-studies: volume ratio bucket; RS >= 60 vs < 60; base flatness
  4. Rule-exit simulation: entry D+1 open, stop = 10-bar low capped at -10%,
     exit on first close below MA150 or stop hit, max 120 bars — by regime

Usage:
    ~/anaconda3/bin/python src/backtest/studies/weinstein_stage2.py
"""

import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import common

VOL_PRIMARY = 1.5
VOL_STRICT = 2.0
MAX_HOLD = 120


def build_signal_mask(m: dict) -> tuple:
    """Weinstein Stage 2 daily-proxy mask plus the matrices sub-studies need."""
    close, volume = m["close"], m["volume"]

    ma150 = close.rolling(150).mean()
    cross = (close > ma150) & (close.shift(1) <= ma150.shift(1))

    ma_chg_pct = (ma150 / ma150.shift(63) - 1).abs() * 100
    flat_base = ma_chg_pct <= 3.0

    under = (close <= ma150).shift(1).rolling(60).sum() >= 40

    prior_max126 = close.shift(1).rolling(126).max()
    clears_resistance = close > 0.98 * prior_max126

    vol_ratio = volume / volume.rolling(50).mean()
    vol_expansion = vol_ratio >= VOL_PRIMARY

    mask = (cross & flat_base & under & clears_resistance & vol_expansion
            & common.tradeable_mask(close, volume))
    return mask, ma150, ma_chg_pct, vol_ratio


def dedup_mask(mask: pd.DataFrame, gap: int = 20) -> pd.DataFrame:
    """Drop an event if the same symbol had one in the prior `gap` bars."""
    arr = mask.to_numpy().copy()
    for j in range(arr.shape[1]):
        rows = np.flatnonzero(arr[:, j])
        last = -gap - 1
        for i in rows:
            if i - last <= gap:
                arr[i, j] = False
            else:
                last = i
    return pd.DataFrame(arr, index=mask.index, columns=mask.columns)


def add_extra_columns(events: pd.DataFrame, mask: pd.DataFrame, m: dict,
                      ma_chg_pct: pd.DataFrame, vol_ratio: pd.DataFrame) -> pd.DataFrame:
    """Attach vol ratio, base flatness and 40/60-bar forward returns.

    Uses the same np.where ordering as common.events_from_mask.
    """
    close = m["close"]
    dates, syms = np.where(mask.reindex_like(close).fillna(False))
    events["vol_ratio"] = vol_ratio.values[dates, syms]
    events["ma150_chg63_pct"] = ma_chg_pct.values[dates, syms]
    for n in [40, 60]:
        fwd_close = close.shift(-n).values[dates, syms]
        events[f"ret_o{n}"] = (fwd_close / events["entry_open"] - 1) * 100
    return events


def simulate_rule_exits(events: pd.DataFrame, m: dict, ma150: pd.DataFrame) -> pd.DataFrame:
    """Entry D+1 open; stop = min low of last 10 bars capped at -10%;
    exit on stop hit (gap fills at open, stop wins on ambiguity) or first
    close below MA150 after entry; time out at MAX_HOLD bars."""
    close = m["close"]
    O, H, L, C = (m[k].to_numpy() for k in ["open", "high", "low", "close"])
    MA = ma150.to_numpy()
    date_pos = {d: i for i, d in enumerate(close.index)}
    sym_pos = {s: j for j, s in enumerate(close.columns)}
    n_rows = len(close.index)

    trades = []
    for ev in events.itertuples():
        i, j = date_pos[ev.date], sym_pos[ev.symbol]
        if i + 1 >= n_rows or np.isnan(O[i + 1, j]):
            continue
        entry = O[i + 1, j]
        stop = max(np.nanmin(L[max(0, i - 9):i + 1, j]), entry * 0.90)
        if entry <= stop:
            continue
        risk = entry - stop

        exit_price, hold, reason = np.nan, np.nan, "open"
        last_close, last_k = np.nan, i + 1
        for k in range(i + 1, min(i + 1 + MAX_HOLD, n_rows)):
            if np.isnan(C[k, j]):
                continue
            last_close, last_k = C[k, j], k
            if L[k, j] <= stop:
                exit_price = O[k, j] if O[k, j] <= stop else stop
                hold, reason = k - i, "stop"
                break
            if C[k, j] < MA[k, j]:
                exit_price, hold, reason = C[k, j], k - i, "ma_cross"
                break
        if reason == "open":
            if np.isnan(last_close):
                continue
            exit_price, hold, reason = last_close, last_k - i, "timeout"

        trades.append({"date": ev.date, "symbol": ev.symbol, "regime": ev.regime,
                       "entry": entry, "stop": stop, "exit": exit_price,
                       "R": (exit_price - entry) / risk, "hold": hold,
                       "reason": reason})
    return pd.DataFrame(trades)


def print_exit_table(trades: pd.DataFrame) -> None:
    def line(name, grp):
        if len(grp) < 10:
            print(f"  {name:<14} n={len(grp)} (too few)")
            return
        r = grp["R"]
        pos, neg = r[r > 0].sum(), r[r < 0].sum()
        pf = pos / -neg if neg < 0 else np.inf
        print(f"  {name:<14} n={len(grp):<5} win {(r > 0).mean() * 100:4.1f}%  "
              f"avg R {r.mean():+5.2f}  med R {r.median():+5.2f}  "
              f"PF {pf:4.2f}  hold {grp['hold'].mean():4.1f}d")

    line("all", trades)
    for regime in ["good", "neutral", "bad"]:
        line(regime, trades[trades["regime"] == regime])


def print_report(events: pd.DataFrame, trades: pd.DataFrame) -> None:
    strict = events[events["vol_ratio"] >= VOL_STRICT]
    print(f"\n{'=' * 76}")
    print(f"WEINSTEIN STAGE 2 BREAKOUT STUDY — "
          f"{events['date'].min().date()} → {events['date'].max().date()}")
    print(f"{'=' * 76}")
    print(f"Events: {len(events)} at volume >= {VOL_PRIMARY}x (primary) | "
          f"{len(strict)} at Weinstein's >= {VOL_STRICT}x")
    print("Returns below are from D+1 OPEN entry to D+n close.")

    print("\n[1] Baseline forward returns (all events, volume >= 1.5x):")
    for n in common.HORIZONS + [40, 60]:
        print(f"  D+{n:<3} {common.stat_line(events[f'ret_o{n}'])}")

    print("\n[1b] Weinstein-strict (volume >= 2x) forward returns:")
    for n in [1, 5, 20, 40, 60]:
        print(f"  D+{n:<3} {common.stat_line(strict[f'ret_o{n}'])}")

    common.print_standard_segments(events, horizons=[1, 5, 20])

    print("\n[Regime] Long horizons (D+40 / D+60) by regime:")
    common.print_table(events, "regime", horizons=[40, 60])

    print("\n[3a] By breakout volume ratio bucket:")
    events["vol_bucket"] = pd.cut(events["vol_ratio"], [1.5, 2, 3, np.inf],
                                  labels=["1.5-2x", "2-3x", ">3x"])
    common.print_table(events, "vol_bucket", horizons=[5, 20, 60])

    print("\n[3b] RS filter at signal (Weinstein demanded improving RS):")
    events["rs_gate"] = np.where(events["rs_rank"] >= 60, "RS >= 60", "RS < 60")
    common.print_table(events, "rs_gate", horizons=[5, 20, 60])

    print("\n[3c] By base flatness (|MA150 change over 63 bars|):")
    events["flat_bucket"] = pd.cut(events["ma150_chg63_pct"], [-0.001, 1, 3],
                                   labels=["<1%", "1-3%"])
    common.print_table(events, "flat_bucket", horizons=[5, 20, 60])

    print("\n[4] Rule-exit simulation (entry D+1 open, stop = 10-bar low capped")
    print("    at -10%, exit on close < MA150 or stop, max 120 bars):")
    print_exit_table(trades)
    reasons = trades["reason"].value_counts()
    print("  exits: " + ", ".join(f"{k} {v}" for k, v in reasons.items()))

    print()
    print(common.CAVEATS)


def main():
    print("Loading study cache...")
    m = common.load_cache()

    print("Scanning for Stage 2 breakout events...")
    mask, ma150, ma_chg_pct, vol_ratio = build_signal_mask(m)
    mask = dedup_mask(mask)
    events = common.events_from_mask(mask, m)
    events = add_extra_columns(events, mask, m, ma_chg_pct, vol_ratio)
    events = common.add_regime_and_rs_buckets(events)
    print(f"  {len(events)} events")

    print("Simulating rule exits...")
    trades = simulate_rule_exits(events, m, ma150)

    print_report(events, trades)

    os.makedirs(common.OUTPUT_DIR, exist_ok=True)
    out_path = os.path.join(common.OUTPUT_DIR, "weinstein_stage2_events.csv")
    events.to_csv(out_path, index=False)
    print(f"\nEvent log → {out_path}")


if __name__ == "__main__":
    main()
