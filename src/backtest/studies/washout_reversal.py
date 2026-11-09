"""
washout_reversal.py — Do 3-day washouts bounce, and does RS rank predict it?

Event: a stock closes down 3 sessions in a row (Day 0 = the 3rd down close),
while the OVERALL market is healthy per the same 5-signal breadth score that
regime.py uses live (score >= +1 → NORMAL/AGGRESSIVE = "good market").

Each event is tagged with the stock's composite RS rank (same 21/63/126-day
blend as the live scanner) as of Day 0, then forward returns are measured at
D+1/2/3/5/10/20 — both from the Day-0 close and from the realistic D+1 open.

Sub-studies reported:
  1. Baseline vs good-market vs bad-market events
  2. Good market, by RS quintile (the core question)
  3. Good market, by 3-day pullback depth
  4. Good market, above vs below the 50 DMA
  5. Good market, RS quintile × depth cross-table (D+5)
  6. Leader washout (RS>=80, above 50 DMA, 3-day drop <= -6%) across regimes

Tradeability filters: close >= Rs 30, 20-day avg turnover >= Rs 1 cr,
>= 130 prior bars (so the 126-day RS leg is real, not NaN).

Usage:
    python src/backtest/studies/washout_reversal.py
"""

import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from data_collection.storage import read_daily, list_stored_symbols
from preprocessing.breadth import compute_market_monitor
from backtest.pointintime import composite_rs_matrix

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "..", "output", "studies")

MIN_BARS = 130
MIN_PRICE = 30.0
MIN_TURNOVER_CR = 1.0
HORIZONS = [1, 2, 3, 5, 10, 20]


def build_matrices() -> dict:
    """Full-history wide matrices (index=date, columns=symbol) for open/close/volume."""
    frames = {"open": {}, "close": {}, "volume": {}}
    symbols = list_stored_symbols()
    for i, symbol in enumerate(symbols, start=1):
        if i % 500 == 0:
            print(f"  Loading [{i}/{len(symbols)}]...")
        df = read_daily(symbol, columns=["date", "open", "close", "volume"])
        # ~400 daily files carry stray intraday rows (2016-18); a real daily
        # bar is always midnight IST. Non-midnight rows would poison the
        # union index and NaN out close.diff() market-wide.
        df = df[df["date"].dt.time == pd.Timestamp("00:00").time()]
        if len(df) < MIN_BARS:
            continue
        df = df.set_index("date")
        for col in frames:
            frames[col][symbol] = df[col]
    return {col: pd.DataFrame(series).sort_index() for col, series in frames.items()}


def breadth_score_series(cm: pd.DataFrame, vm: pd.DataFrame) -> pd.Series:
    """
    The regime.py 5-signal score, vectorized over every date instead of just
    the latest row: ratio5, ratio10, up25q-dn25q, pct40ma, pct20ma each
    contribute +1 bullish / -1 bearish / 0 neutral. Same thresholds.
    """
    mm = compute_market_monitor(cm, vm)

    ma20 = cm.rolling(20).mean()
    pct20ma = (cm > ma20).sum(axis=1) / (cm.notna() & ma20.notna()).sum(axis=1) * 100

    def zone(series, bull, bear):
        return pd.Series(np.where(series > bull, 1, np.where(series < bear, -1, 0)),
                         index=series.index).where(series.notna(), 0)

    score = (
        zone(mm["ratio5"], 2, 0.5)
        + zone(mm["ratio10"], 2, 0.5)
        + zone(mm["up25q"] - mm["dn25q"], 0, 0)
        + zone(mm["pct40ma"], 60, 40)
        + zone(pct20ma, 60, 40)
    )
    return score


def find_events(close: pd.DataFrame, open_: pd.DataFrame, volume: pd.DataFrame,
                score: pd.Series, rs: pd.DataFrame) -> pd.DataFrame:
    """One row per (symbol, Day 0) where the stock logged its 3rd straight down close."""
    chg = close.diff()
    down = (chg < 0) & close.notna() & close.shift(1).notna()
    third_down = down & down.shift(1) & down.shift(2) & ~down.shift(3, fill_value=False)

    turnover_cr = (close * volume / 1e7).rolling(20).mean()
    enough_history = close.notna().cumsum() >= MIN_BARS
    tradeable = (close >= MIN_PRICE) & (turnover_cr >= MIN_TURNOVER_CR) & enough_history

    mask = third_down & tradeable
    depth = close.pct_change(3, fill_method=None) * 100
    ma50 = close.rolling(50).mean()

    dates, syms = np.where(mask)
    events = pd.DataFrame({
        "date": close.index[dates],
        "symbol": close.columns[syms],
        "close": close.values[dates, syms],
        "depth_3d": depth.values[dates, syms],
        "rs_rank": rs.values[dates, syms],
        "above_50ma": close.values[dates, syms] > ma50.values[dates, syms],
        "breadth_score": score.values[dates],
    })

    next_open = open_.shift(-1)
    events["entry_open"] = next_open.values[dates, syms]
    for n in HORIZONS:
        fwd_close = close.shift(-n).values[dates, syms]
        events[f"ret_c{n}"] = (fwd_close / events["close"] - 1) * 100
        events[f"ret_o{n}"] = (fwd_close / events["entry_open"] - 1) * 100
    return events


def stat_line(returns: pd.Series) -> str:
    r = returns.dropna()
    if len(r) < 30:
        return f"n={len(r)} (too few)"
    return (f"med {r.median():+5.2f}%  mean {r.mean():+5.2f}%  "
            f"win {(r > 0).mean() * 100:4.1f}%")


def print_table(events: pd.DataFrame, group_col: str, ret_prefix: str = "ret_o") -> None:
    for label, grp in events.groupby(group_col, observed=True):
        cells = "  |  ".join(f"D+{n} {stat_line(grp[f'{ret_prefix}{n}'])}"
                             for n in [1, 5, 20])
        print(f"  {str(label):<22} n={len(grp):<6} {cells}")


def print_report(events: pd.DataFrame) -> None:
    good = events[events["breadth_score"] >= 1].copy()
    bad = events[events["breadth_score"] <= -2]
    neutral = events[(events["breadth_score"] >= -1) & (events["breadth_score"] < 1)]

    print(f"\n{'=' * 76}")
    print(f"WASHOUT REVERSAL STUDY — 3 consecutive down closes, "
          f"{events['date'].min().date()} → {events['date'].max().date()}")
    print(f"{'=' * 76}")
    print(f"Events: {len(events)} total | good market (score>=+1): {len(good)} | "
          f"neutral: {len(neutral)} | bad (<=-2): {len(bad)}")
    print("Returns below are from D+1 OPEN entry to D+n close unless noted.")

    print("\n[1] Market regime at the event (does a good tape matter?):")
    for name, grp in [("good market", good), ("neutral", neutral), ("bad market", bad)]:
        cells = "  |  ".join(f"D+{n} {stat_line(grp[f'ret_o{n}'])}" for n in [1, 5, 20])
        print(f"  {name:<22} n={len(grp):<6} {cells}")

    rs_bins = [0, 20, 40, 60, 80, 100]
    rs_labels = ["RS 0-20", "RS 20-40", "RS 40-60", "RS 60-80", "RS 80-100"]
    good["rs_bucket"] = pd.cut(good["rs_rank"], rs_bins, labels=rs_labels)

    print("\n[2] Good market only — by composite RS quintile at Day 0:")
    print_table(good, "rs_bucket")

    depth_bins = [-np.inf, -10, -6, -3, 0]
    depth_labels = ["deeper than -10%", "-10% to -6%", "-6% to -3%", "-3% to 0%"]
    good["depth_bucket"] = pd.cut(good["depth_3d"], depth_bins, labels=depth_labels)

    print("\n[3] Good market only — by 3-day pullback depth:")
    print_table(good, "depth_bucket")

    print("\n[4] Good market only — trend context at Day 0:")
    good["trend"] = np.where(good["above_50ma"], "above 50 DMA", "below 50 DMA")
    print_table(good, "trend")

    print("\n[5] Good market — median D+5 return, RS quintile x depth (n in parens):")
    pivot_med = good.pivot_table(values="ret_o5", index="rs_bucket",
                                 columns="depth_bucket", aggfunc="median", observed=True)
    pivot_n = good.pivot_table(values="ret_o5", index="rs_bucket",
                               columns="depth_bucket", aggfunc="count", observed=True)
    header = "".join(f"{c:>20}" for c in pivot_med.columns)
    print(f"  {'':<12}{header}")
    for idx in pivot_med.index:
        cells = "".join(
            f"{pivot_med.loc[idx, c]:>+12.2f} ({pivot_n.loc[idx, c]:>4.0f})"
            if pd.notna(pivot_med.loc[idx, c]) else f"{'—':>19}"
            for c in pivot_med.columns)
        print(f"  {str(idx):<12}{cells}")

    print("\n[6] Leader washout (RS>=80, above 50 DMA, depth<=-6%) by market regime:")
    leader = (events["rs_rank"] >= 80) & events["above_50ma"] & (events["depth_3d"] <= -6)
    for name, grp in [("good market", events[leader & (events["breadth_score"] >= 1)]),
                      ("neutral", events[leader & (events["breadth_score"].between(-1, 0))]),
                      ("bad market", events[leader & (events["breadth_score"] <= -2)])]:
        cells = "  |  ".join(f"D+{n} {stat_line(grp[f'ret_o{n}'])}" for n in [1, 5, 20])
        print(f"  {name:<22} n={len(grp):<6} {cells}")

    print("\nNotes:")
    print("  - Bad-market events cluster in corrections, so their forward windows")
    print("    overlap heavily and ride the market's own rebound (beta, not alpha).")
    print("  - Forward windows overlap across events of the same symbol; stats are")
    print("    per-event, not a portfolio equity curve.")
    print("  - Stocks suspended/delisted inside the window drop out of that horizon's")
    print("    stats (mild exit-survivorship).")
    print("  - No historical ASM/GSM exclusion; no costs/slippage modelled.")
    print("  - Split repair: run integrity.py --scan first if results look off.")


def main():
    print("Building full-history matrices from per-symbol parquets...")
    m = build_matrices()
    close, open_, volume = m["close"], m["open"], m["volume"]
    print(f"  {close.shape[1]} symbols, {close.index.min().date()} → {close.index.max().date()}")

    print("Computing breadth score and composite RS ranks...")
    score = breadth_score_series(close, volume)
    rs = composite_rs_matrix(close)

    print("Scanning for 3-consecutive-down-day events...")
    events = find_events(close, open_, volume, score, rs)
    print(f"  {len(events)} events")

    print_report(events)

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    out_path = os.path.join(OUTPUT_DIR, "washout_reversal_events.csv")
    events.to_csv(out_path, index=False)
    print(f"\nEvent log → {out_path}")


if __name__ == "__main__":
    main()
